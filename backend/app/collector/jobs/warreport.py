"""War Report 每日采集：赛季榜（players / clans）+ 热门配兵。

与官方采集（``app/coc``）是两条独立链路：上游是第三方只读 API
（https://api.warreport.app），不需要 Token，也没有令牌桶。

四条硬约束：

* **赛季榜按快照日期分 scope 全量替换**（``kind × 32000000 × None × 日期``）。
  每个 scope 单独 ``commit`` —— ``replace_rankings`` 拿的是事务级顾问锁，
  长事务会把另一个采集进程一直挡在锁外。
* **配兵与赛季发现解耦**。``discover_snapshots()`` 返回 ``[]`` 只表示"没探到
  快照"，**不是**"该清空赛季"：阵容仍要照常刷新，否则赛季侧的异常会顺手
  让阵容页静默停更。
* **单 scope 失败不能拖垮整轮**：``rollback`` 后记明细继续，由 ``run_job``
  判成 ``partial``。但**探测阶段的异常要冒泡** —— 那是整轮失败，不是
  "今天没有快照"。
* 时间只认带时区的 ``now``（调用方注入，缺省取 UTC）。

不 import FastAPI（AGENTS.md 架构边界）：``APP_ROLE=collector`` 时要能脱离
HTTP 层单独跑。
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.collector.rankings_service import RankingKind, replace_rankings
from app.db.models import Ranking, WarReportArmy
from app.warreport.client import WarReportClient
from app.warreport.mappers import army_row, clan_item, player_item
from app.warreport.snapshots import discover_snapshots

logger = logging.getLogger("coc.collector.warreport")

#: 落库 scope 的地区恒为全服。War Report 的赛季榜没有"地区"维度，沿用官方榜的
#: 全服 id，前端才能用同一套 scope 读两类榜。
GLOBAL_LOCATION_ID = 32000000

#: 配兵整表替换的顾问锁 key（``WRAR`` 的 ASCII）。**与榜单的 ``RANK`` 不是同一把**：
#: 两张表各自独立替换，共用一把锁只会让两个 job 互相干等。
#: 事务级（``_xact_``）：``COMMIT``/``ROLLBACK`` 自动释放。
_ARMIES_WRITE_LOCK_KEY = 0x57524152

#: 探测锚点只认这两类 kind 的 ``season_id``。别的 kind 的 ``season_id``
#: （例如 Legend 赛季榜的 ``2026-10``）不是快照日期，拿来当锚点会探错。
_SNAPSHOT_KINDS = (RankingKind.wr_season_players, RankingKind.wr_season_clans)

#: (上游路径, kind, mapper)。顺序即采集顺序。
_SNAPSHOT_SCOPES: tuple[
    tuple[str, RankingKind, Callable[[dict[str, Any]], dict[str, Any] | None]], ...
] = (
    ("/locations/global/rankings/players", RankingKind.wr_season_players, player_item),
    ("/locations/global/rankings/clans", RankingKind.wr_season_clans, clan_item),
)


async def collect_warreport(
    client: WarReportClient, session: AsyncSession, now: dt.datetime | None = None
) -> dict[str, Any]:
    """采一轮 War Report：最近最多 3 个赛季快照 × 2 类榜 + 配兵。

    返回 ``{"items_ok": n, "items_failed": m, "detail": [...]}`` ——
    ``items_ok`` 数的是**成功的 scope**，不是行数（``run_job`` 只认这个口径）。
    """
    now = now or dt.datetime.now(dt.UTC)

    # 库里的快照日期只作探测锚点：discover_snapshots 会自己合并新探到的日期、
    # 也会在锚点不可信时回退逐日回溯。``IS NOT NULL`` 不能省 —— 同一个 kind
    # 若哪天混进别的 scope，NULL 会让 ``known[0]`` 变成一个没意义的锚点。
    known = (
        await session.execute(
            select(Ranking.season_id)
            .where(
                Ranking.kind.in_([str(kind) for kind in _SNAPSHOT_KINDS]),
                Ranking.season_id.is_not(None),
            )
            .distinct()
            .order_by(Ranking.season_id.desc())
        )
    ).scalars().all()

    # **不 catch**：探测阶段的网络错误/5xx 是整轮失败，交给 run_job 记 failed。
    # 吞掉会以"0 个 scope"收场，看起来就像"今天没有新快照"。
    snapshots = await discover_snapshots(client, list(known), now.date())

    ok = 0
    failed = 0
    failures: list[str] = []

    for snapshot in snapshots:
        for path, kind, mapper in _SNAPSHOT_SCOPES:
            try:
                raw = await client.get_json(path, {"season": snapshot})
                if not isinstance(raw, list):
                    # 上游改了响应形状时**必须响亮失败**：把 dict 当空列表处理
                    # 会静默清空该快照的榜单，而 run_job 还记 success。
                    raise ValueError(f"{path} 响应不是列表: {str(raw)[:200]}")
                # 非对象元素先挡掉：mapper 的入参是 dict，别让一条脏元素把整个
                # scope 打挂（那会让该快照的榜永远停在旧版本）。
                items = [
                    item
                    for item in (
                        mapper(entry) for entry in raw if isinstance(entry, dict)
                    )
                    if item is not None
                ]
                written = await replace_rankings(
                    session,
                    kind,
                    GLOBAL_LOCATION_ID,
                    None,
                    snapshot,
                    items,
                    now=now,
                )
                # **提交必须在 try 里**：commit 也可能失败（连接断、锁等待超时、
                # 约束冲突）。放到 except 之外的话，一次提交失败会直接冒泡出本函数
                # —— 剩下的 scope 与配兵都不再采，run_job 把整轮记成 failed 且
                # items_ok=0，而前面成功的 scope 其实已经落库了。
                await session.commit()
            except Exception as exc:  # noqa: BLE001 - 单个 scope 失败不能拖垮整轮
                failed += 1
                failures.append(f"{kind}/{snapshot}: {exc}")
                logger.warning("warreport %s/%s 采集失败: %s", kind, snapshot, exc)
                # 前面成功的 scope 已经提交，这里只回滚当前这个
                await session.rollback()
                continue
            ok += 1
            logger.debug("warreport %s/%s 写入 %s 条", kind, snapshot, written)

    try:
        written = await _replace_armies(client, session, now)
    except Exception as exc:  # noqa: BLE001
        failed += 1
        failures.append(f"armies: {exc}")
        logger.warning("warreport armies 采集失败: %s", exc)
        await session.rollback()
    else:
        ok += 1
        logger.debug("warreport armies 写入 %s 条", written)

    return _result(ok, failed, failures)


async def _replace_armies(
    client: WarReportClient, session: AsyncSession, now: dt.datetime
) -> int:
    """``GET /armies`` → 整表替换 ``warreport_armies`` → commit，返回写入条数。

    整表替换而不是 upsert：上游按使用率降序给一份完整清单，掉出榜单的配兵
    必须跟着消失。
    """
    raw = await client.get_json("/armies")
    if not isinstance(raw, list):
        # 与赛季榜同理：形状变了要响亮失败，不能把"空"当成"该清空整表"。
        raise ValueError(f"/armies 响应不是列表: {str(raw)[:200]}")

    # 过滤、去重、编号在同一个循环里完成：``position`` 传的是「已接受行数 + 1」，
    # 也就是这一行**最终**的编号 —— 不先按原始下标编一遍再回头重排。``army_row``
    # 会丢掉缺 not-null 字段的行，按原始下标编号会在前端留下 1、3、4 这样的空洞。
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row = army_row(entry, len(rows) + 1, now)
        if row is None:
            continue
        # 同一次响应里出现两条同 key 时，唯一约束会让**整次** commit 失败 ——
        # 那时 DELETE 已执行但事务回滚，数据是安全的，可阵容会永远停在旧版本
        # （只有 collector_runs.error 能看到原因）。去重把这种上游脏数据降级成
        # 无害事件：保留先出现的那条。
        if row["canonical_key"] in seen:
            logger.warning(
                "warreport armies 重复的 canonical_key=%s，已跳过",
                row["canonical_key"],
            )
            continue
        seen.add(row["canonical_key"])
        rows.append(row)

    # 锁 → 删 → 插 → commit。锁是事务级的，commit 时自动释放。
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": _ARMIES_WRITE_LOCK_KEY},
    )
    await session.execute(delete(WarReportArmy))
    session.add_all([WarReportArmy(**row) for row in rows])
    await session.commit()
    return len(rows)


def _result(ok: int, failed: int, failures: list[str]) -> dict[str, Any]:
    """统一返回形状。``detail`` 只在有失败时带 —— 明细太长，成功时没有价值。"""
    if failures:
        return {"items_ok": ok, "items_failed": failed, "detail": failures[:50]}
    return {"items_ok": ok, "items_failed": failed}
