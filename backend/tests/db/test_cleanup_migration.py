"""数据清理迁移的语义测试。

迁移 0011（``drop_non_global_rankings``）是**破坏性**的：它删掉三类已停采的
地区榜，以及所有非全服地区的部落/玩家榜。这类迁移最容易出的错是**删多了**
—— 尤其赛季榜：它的 ``location_id`` 是 NULL，scope 是
``(league_id, season_id)``，跟地区榜完全不同。误删赛季榜的话，传奇联赛的
赛季排行会静默消失，而且没有任何报错。

所以这里把「删哪些、不删哪些」钉死。
"""

from __future__ import annotations

import datetime as dt
from datetime import UTC

from sqlalchemy import select

from app.collector.rankings_service import RankingKind
from app.db.models import Ranking

GLOBAL = 32000000
CN = 32000001


async def test_migration_keeps_global_clans_and_players(session):
    """全服的部落榜与玩家榜必须留下。"""
    now = dt.datetime.now(UTC)
    session.add_all([
        Ranking(kind=str(RankingKind.clans), location_id=GLOBAL, rank=1,
                tag="#G1", name="G1", fetched_at=now),
        Ranking(kind=str(RankingKind.players), location_id=GLOBAL, rank=1,
                tag="#GP1", name="GP1", fetched_at=now),
    ])
    await session.commit()

    await _run_migration(session)

    rows = (await session.execute(select(Ranking))).scalars().all()
    assert {r.kind for r in rows} == {
        str(RankingKind.clans),
        str(RankingKind.players),
    }
    assert all(r.location_id == GLOBAL for r in rows)


async def test_migration_keeps_season_rankings(session):
    """**赛季榜必须留下** —— 它的 location_id 是 NULL，scope 完全不同。

    这是最容易删多的一处：赛季榜还在用（``jobs/seasons.py`` 采集，前端
    「赛季排行」页展示）。
    """
    now = dt.datetime.now(UTC)
    session.add(
        Ranking(kind=str(RankingKind.season_players), league_id=29000022,
                season_id="2026-09", rank=1, tag="#S1", name="S1",
                fetched_at=now),
    )
    await session.commit()

    await _run_migration(session)

    rows = (await session.execute(select(Ranking))).scalars().all()
    assert len(rows) == 1
    assert rows[0].kind == str(RankingKind.season_players)


async def test_migration_drops_removed_kinds_and_other_locations(session):
    """三类已停采的榜 + 非全服的地区榜都要删掉。"""
    now = dt.datetime.now(UTC)
    session.add_all([
        # 要删的：三类废榜
        Ranking(kind="capitals", location_id=CN, rank=1, name="首都",
                fetched_at=now),
        Ranking(kind="clans_builder_base", location_id=CN, rank=1, tag="#BB",
                name="BB", fetched_at=now),
        Ranking(kind="players_builder_base", location_id=CN, rank=1, tag="#PB",
                name="PB", fetched_at=now),
        # 要删的：非全服地区的正常榜
        Ranking(kind=str(RankingKind.clans), location_id=CN, rank=1, tag="#C1",
                name="C1", fetched_at=now),
        # 要留的
        Ranking(kind=str(RankingKind.clans), location_id=GLOBAL, rank=1,
                tag="#G1", name="G1", fetched_at=now),
    ])
    await session.commit()

    await _run_migration(session)

    rows = (await session.execute(select(Ranking))).scalars().all()
    assert len(rows) == 1
    assert rows[0].tag == "#G1"


async def _run_migration(session) -> None:
    """按迁移里的 SQL 原文执行一遍 —— 直接 import 迁移模块，保证测的就是它。"""
    from sqlalchemy import text

    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "migrations" / "versions" / (
        "0011_drop_non_global_rankings.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0011", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # 迁移用 op.execute 跑裸 SQL；这里直接取它构造出来的语句执行。
    statements = _migration_statements(mod)
    for sql in statements:
        await session.execute(text(sql))
    await session.commit()


def _migration_statements(mod) -> list[str]:
    """从迁移模块里取出它会执行的 SQL。

    迁移用 ``op.execute``，直接跑会打 alembic 的 op 对象。这里用一个假的
    op 拦截 execute，把语句收下来。
    """
    import types

    captured: list[str] = []

    class FakeOp:
        @staticmethod
        def execute(sql):
            captured.append(sql)

    fake = types.SimpleNamespace(execute=FakeOp.execute)
    mod.op = fake
    mod.upgrade()
    return captured
