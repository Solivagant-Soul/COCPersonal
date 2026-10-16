"""运维 CLI。

**只有一个命令：``import-game-data``。**

原计划里还有 ``create-admin``，已按 R3 裁定删除 —— 后台认证走环境变量
``ADMIN_USERNAME`` / ``ADMIN_PASSWORD``，规格中不存在任何管理员表。保留那个
命令等于凭空引入一张表、或制造第二条与后台互不知情的凭据来源。
**管理员账号只在 ``.env`` 里配置，不入库。**
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import Counter
from pathlib import Path

from app.content.game_data import fetch_units_data, import_upgrade_items, units_to_rows

logger = logging.getLogger("coc.cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="COC 后端运维命令",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    imp = sub.add_parser(
        "import-game-data",
        help="导入升级数据（npm clashofclans.js 数据集）",
    )
    imp.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="tarball 缓存目录。给出后可离线重跑",
    )
    imp.add_argument(
        "--dry-run",
        action="store_true",
        help="只解析与统计，不写库",
    )
    return parser


async def cmd_import_game_data(
    cache_dir: Path | None = None,
    dry_run: bool = False,
    session=None,
) -> int:
    """导入升级数据，返回写入行数。

    **只把 ``RAW_UNITS`` 交给转换层**：``RAW_SUPER_UNITS`` 是超级兵种，结构是
    ``resourceCost`` + ``cooldown`` 而非 ``upgrade.cost`` 数组，产生不了等级行。
    这里显式丢弃，而不是指望转换层静默跳过 —— 静默跳过会让"为什么少了几百行"
    变成一个查不到答案的问题。
    """
    from app.content.game_data import (
        RAW_SUPER_UNITS_KEY,
        RAW_UNITS_KEY,
        import_upgrade_items,
        units_to_rows,
    )

    # fetch_units_data 用**模块级**名字而非这里再 import 一次：
    # 函数内 import 会创建局部绑定，测试 monkeypatch app.cli.fetch_units_data
    # 就完全不起作用 —— 表现为测试"意外地"真联网跑了一遍真实数据。
    data = await fetch_units_data(cache_dir=cache_dir)
    units = data.get(RAW_UNITS_KEY) or []
    super_units = data.get(RAW_SUPER_UNITS_KEY) or []
    logger.info(
        "读到 %s 条单位定义，丢弃 %s 条超级兵种", len(units), len(super_units)
    )

    rows = units_to_rows(units)
    by_category = Counter(r["category"] for r in rows)
    logger.info("生成 %s 行：%s", len(rows), dict(by_category))

    if dry_run:
        print(f"dry-run：将写入 {len(rows)} 行 {dict(by_category)}")
        return len(rows)

    if session is not None:
        written = await import_upgrade_items(session, rows)
    else:
        written = await _import_with_own_session(rows)
    print(f"已写入 {written} 行：{dict(by_category)}")
    return written


async def _import_with_own_session(rows) -> int:
    from app.db.session import async_sessionmaker

    maker = async_sessionmaker()
    session = await maker.__aenter__()
    try:
        return await import_upgrade_items(session, rows)
    finally:
        await session.__aexit__(None, None, None)
        await session.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    if args.command == "import-game-data":
        count = asyncio.run(
            cmd_import_game_data(cache_dir=args.cache_dir, dry_run=args.dry_run)
        )
        return 0 if count >= 0 else 1
    return 1


# 让 `from app.cli import fetch_units_data` 成立：测试要 monkeypatch 这个名字，
# 必须在 app.cli 的命名空间里真的存在。
from app.content.game_data import fetch_units_data  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())