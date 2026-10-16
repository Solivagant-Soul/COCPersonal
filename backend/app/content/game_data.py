"""npm 数据集 → ``upgrade_items`` 表。

数据源是 MIT 许可的 ``clashofclans.js@4.0.5``，其 ``raw.json`` 有 2073 条单位定义
（troop 599 / spell 111 / hero 513 / equipment 850）。

**全程用 ``urllib`` + ``tarfile``，不调 npm、不调 Node.js**（规格 §10.3）——
部署机不该为了导一份数据先装一个 Node 运行时。

三条硬约定：

1. **``upgrade.cost[i]`` → ``level = i + 1``**，表示"从 level 升到 level+1"。
   索引 0 对应 1→2 级。这是最容易搞错一格的地方 —— 差一格会让用户算出
   完全错误的升级成本。
2. **超级兵种产生不了等级行。** 它们在 ``RAW_SUPER_UNITS`` 里，结构是
   ``resourceCost`` + ``cooldown`` 而非 ``upgrade.cost`` 数组。这里防御性跳过。
3. **``name_zh`` 一律留空。** 翻译由 Task 16 的接口层负责，导入阶段不猜。
   填了来源不明的翻译比留空更糟 —— 用户会以为那是准确的。
"""

from __future__ import annotations

import json
import logging
import tarfile
import urllib.request
from pathlib import Path
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UpgradeCategory, UpgradeItem

logger = logging.getLogger("coc.content")

#: npm 包名与版本。锁版本是因为上游发新版可能改字段结构，升级要显式决定。
NPM_PACKAGE = "clashofclans.js"
NPM_VERSION = "4.0.5"
NPM_REGISTRY = f"https://registry.npmjs.org/{NPM_PACKAGE}"

#: tarball 内的数据文件路径。
RAW_UNITS_KEY = "RAW_UNITS"
RAW_SUPER_UNITS_KEY = "RAW_SUPER_UNITS"

#: 只接受这四类。building 由另一条路径处理（其解锁条件结构不同）；
#: 未列出的类别既不产生行也不报错 —— 上游新增类别不该让导入崩掉。
_ACCEPTED_CATEGORIES = frozenset(
    {
        UpgradeCategory.troop,
        UpgradeCategory.spell,
        UpgradeCategory.hero,
        UpgradeCategory.equipment,
    }
)

#: ``upgrade.resource`` 的取值 → 列名。未列出的（如 Builder Elixir，
#: 基地专用货币）不写任何成本列：宁可留空，也不要记成普通货币。
_RESOURCE_COLUMNS = {
    "Gold": "gold",
    "Elixir": "elixir",
    "Dark Elixir": "dark_elixir",
}


async def fetch_units_data(cache_dir: Path | None = None) -> dict[str, Any]:
    """下载 npm 包并读出单位定义。

    返回 ``{"RAW_UNITS": [...], "RAW_SUPER_UNITS": [...]}``。

    ``cache_dir`` 给出时把 tarball 落盘 —— 离线重跑与反复调试时不必每次都联网。
    """
    tarball_path = await _download_tarball(cache_dir)
    raw = _read_raw_json(tarball_path)
    return {
        RAW_UNITS_KEY: raw.get(RAW_UNITS_KEY, []),
        RAW_SUPER_UNITS_KEY: raw.get(RAW_SUPER_UNITS_KEY, []),
    }


async def _download_tarball(cache_dir: Path | None) -> Path:
    """取 tarball，优先用缓存。返回本地文件路径。"""
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached = cache_dir / f"{NPM_PACKAGE}-{NPM_VERSION}.tgz"
        if cached.exists() and cached.stat().st_size > 0:
            logger.info("用缓存的 tarball: %s", cached)
            return cached
        target = cached
    else:
        target = Path(f"{NPM_PACKAGE}-{NPM_VERSION}.tgz")

    url = await _resolve_tarball_url()
    logger.info("下载 %s", url)
    # 超时必须有：网络不通时 urllib 会一直挂着，部署流程就此卡死
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 - 固定 registry
        payload = resp.read()
    target.write_bytes(payload)
    return target


async def _resolve_tarball_url() -> str:
    """从 npm registry 元信息里取 tarball 地址。

    请求 ``/{package}/{version}``（单版本文档）。请求包根会拿到**全部版本**的
    元信息，几十 KB 里只有 ``latest`` 的 dist 可用，指定版本反而拿不到 ——
    实测会抛 ``KeyError: 'versions'``。
    """
    url = f"{NPM_REGISTRY}/{NPM_VERSION}"
    with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 - 固定 registry
        meta = json.loads(resp.read().decode("utf-8"))
    # 单版本文档把 dist 直接放在顶层；老形状仍包一层 versions
    dist = meta.get("dist")
    if dist is None:
        dist = meta.get("versions", {}).get(NPM_VERSION, {}).get("dist")
    tarball = (dist or {}).get("tarball")
    if not tarball:
        raise RuntimeError(
            f"npm registry 返回的元信息缺少 tarball 地址（version={NPM_VERSION}）"
        )
    return tarball


def _read_raw_json(tarball_path: Path) -> dict[str, Any]:
    """从 tarball 里读出 ``package/dist/util/raw.json``。

    不用 ``extractall`` —— 那会把包里的任意路径写到磁盘。npm 包完全可控，
    但这是从外部下载的压缩包，逐成员读更稳。
    """
    member = "package/dist/util/raw.json"
    with tarfile.open(tarball_path, "r:gz") as tar:
        try:
            handle = tar.extractfile(member)
        except KeyError as exc:
            names = tar.getnames()[:5]
            raise RuntimeError(
                f"tarball 里没有 {member}（前几个成员：{names}）—— 上游改了目录结构"
            ) from exc
        if handle is None:
            raise RuntimeError(f"tarball 里的 {member} 不是普通文件")
        return json.loads(handle.read().decode("utf-8"))


def units_to_rows(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """单位定义数组 → ``upgrade_items`` 行。

    **一个单位产生 N 行**：``upgrade.cost[i]`` → ``level = i + 1``（升到 level+1）。

    跳过的条目（静默，不报错）：类别不在四类之内；``upgrade`` 或
    ``upgrade.cost`` 缺失（超级兵种就是这种结构）。上游数据里混进未知结构时，
    整个导入失败比跳过几条更糟。
    """
    rows: list[dict[str, Any]] = []
    for unit in units:
        if not isinstance(unit, dict):
            continue
        category = unit.get("category")
        if category not in _ACCEPTED_CATEGORIES:
            continue

        upgrade = unit.get("upgrade")
        if not isinstance(upgrade, dict):
            continue
        costs = upgrade.get("cost")
        if not isinstance(costs, list) or not costs:
            continue

        times = upgrade.get("time")
        times = times if isinstance(times, list) else []
        resource = upgrade.get("resource")
        column = _RESOURCE_COLUMNS.get(resource) if isinstance(resource, str) else None

        unlock = unit.get("unlock")
        unlock = unlock if isinstance(unlock, dict) else {}
        village = unit.get("village") or "home"

        for index, cost in enumerate(costs):
            row: dict[str, Any] = {
                "category": str(category),
                "name": unit.get("name"),
                "village": village,
                # 索引 0 表示 1 → 2 级
                "level": index + 1,
                "gold": None,
                "elixir": None,
                "dark_elixir": None,
                "build_time_seconds": None,
                "builder_count": None,
                "required_townhall_level": unlock.get("hall"),
                "required_lab_level": None,
                "required_builder_base_level": None,
                # 翻译与备注不在导入阶段猜：填了来源不明的翻译比留空更糟
                "name_zh": None,
                "notes": None,
            }
            # Builder Elixir 等未列出的资源不写任何成本列，宁可留空
            if column is not None:
                row[column] = cost
            if index < len(times) and isinstance(times[index], (int, float)):
                row["build_time_seconds"] = int(times[index])
            # 基地建筑等级只对基地单位有意义
            if village == "builderBase":
                row["required_builder_base_level"] = unlock.get("buildingLevel")
            rows.append(row)

    return rows


async def import_upgrade_items(session: AsyncSession, rows: list[dict[str, Any]]) -> int:
    """按 ``(category, name, village, level)`` upsert，返回 ``len(rows)``。

    **返回值恒等于输入行数**（R5 裁定），不是"实际变更行数"。调用方要的是
    "我提交了多少条"，而"变更了多少条"依赖 DB 状态、还会因方言而异。

    幂等是硬要求（规格 §10.3 第 8 条）：重复执行必须安全。
    """
    if not rows:
        return 0

    stmt = pg_insert(UpgradeItem).values(rows)
    # **只更新"权威数据"列。** ``name_zh`` 与 ``builder_count`` 由人工/接口层填写
    # （导入阶段一律 None），把它们放进 set_ 等于让每次重跑都把人工标注清空。
    # ``test_import_does_not_overwrite_manual_name_zh`` 锁住这一点。
    update_cols = {
        "gold": stmt.excluded.gold,
        "elixir": stmt.excluded.elixir,
        "dark_elixir": stmt.excluded.dark_elixir,
        "build_time_seconds": stmt.excluded.build_time_seconds,
        "required_townhall_level": stmt.excluded.required_townhall_level,
        "required_lab_level": stmt.excluded.required_lab_level,
        "required_builder_base_level": stmt.excluded.required_builder_base_level,
        "notes": stmt.excluded.notes,
    }
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["category", "name", "village", "level"],
            set_=update_cols,
        )
    )
    await session.commit()
    return len(rows)