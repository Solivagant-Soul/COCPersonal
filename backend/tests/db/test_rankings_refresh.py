"""排行榜「按 scope 全量替换」刷新（§5.4）。

本任务的核心不变量只有一条，但它极容易被实现错：

**刷 `kind=X, location_id=Y` 时必须删掉该 scope 下全部行再批量插入。**

如果改成逐条 upsert，已经掉榜的条目会永久残留在库里 —— 用户看到的是一份
"半年前的榜单 + 今天的新增"，而 API 返回 200，没有任何报错提示。这个缺陷
不会让任何测试变红，除非专门去测它，所以下面第一条测试就是为它写的。

scope 三元组 `(kind, location_id, league_id, season_id)` 共同确定一份榜单：
刷地区榜不能碰到别的地区，刷赛季榜不能碰到别的赛季。
"""

import pytest
from sqlalchemy import event, func, select

from app.collector.rankings_service import RankingKind, replace_rankings
from app.db.models import Ranking

CN = 32000001  # 中国
US = 32000002  # 美国


def _clan(rank: int, tag: str, name: str, previous: int | None = None) -> dict:
    return {
        "tag": tag,
        "name": name,
        "rank": rank,
        "previousRank": previous,
        "clanLevel": 12,
        "members": 40,
        "points": 5000,
    }


# --------------------------------------------------------------------------- #
# 核心：掉榜条目必须消失
# --------------------------------------------------------------------------- #


async def test_replace_rankings_removes_entries_that_dropped_off_the_board(session):
    """两条榜单刷成一条 —— #BBB 必须消失。

    逐条 upsert 的实现会让这条测试变红，这正是它存在的理由。
    """
    await replace_rankings(
        session,
        RankingKind.clans,
        CN,
        None,
        None,
        [
            _clan(1, "#AAA", "A"),
            _clan(2, "#BBB", "B"),
        ],
    )
    await replace_rankings(
        session, RankingKind.clans, CN, None, None, [_clan(1, "#AAA", "A")]
    )

    tags = (
        await session.execute(
            select(Ranking.tag).where(
                Ranking.kind == RankingKind.clans, Ranking.location_id == CN
            )
        )
    ).scalars().all()
    assert tags == ["#AAA"]


async def test_replace_rankings_returns_written_row_count(session):
    """返回值 = 实际写入条数，供采集器写进 CollectorRun.items_ok。"""
    written = await replace_rankings(
        session,
        RankingKind.clans,
        CN,
        None,
        None,
        [_clan(1, "#AAA", "A"), _clan(2, "#BBB", "B")],
    )
    assert written == 2


async def test_replace_rankings_with_empty_list_clears_the_scope(session):
    """官方返回空 = 这个榜单真的空了，必须清空而不是留着旧数据。

    常见错误实现是"空列表就跳过"，于是榜单永远停在最后一次非空的那版。
    """
    await replace_rankings(session, RankingKind.clans, CN, None, None, [_clan(1, "#AAA", "A")])
    await replace_rankings(session, RankingKind.clans, CN, None, None, [])

    count = (
        await session.execute(
            select(func.count())
            .select_from(Ranking)
            .where(Ranking.location_id == CN)
        )
    ).scalar_one()
    assert count == 0


# --------------------------------------------------------------------------- #
# scope 隔离：刷一个不能碰另一个
# --------------------------------------------------------------------------- #


async def test_replace_rankings_does_not_touch_other_scope(session):
    await replace_rankings(session, RankingKind.clans, CN, None, None, [_clan(1, "#AAA", "A")])
    await replace_rankings(session, RankingKind.clans, US, None, None, [_clan(1, "#CCC", "C")])

    await replace_rankings(session, RankingKind.clans, CN, None, None, [_clan(2, "#DDD", "D")])

    rows = (
        await session.execute(
            select(Ranking.location_id, Ranking.tag)
            .where(Ranking.kind == RankingKind.clans)
            .order_by(Ranking.location_id)
        )
    ).all()
    assert rows == [(CN, "#DDD"), (US, "#CCC")]


async def test_replace_rankings_does_not_touch_other_kind_in_same_location(session):
    """同一个地区下，clans 榜刷新不能碰 players 榜。"""
    await replace_rankings(session, RankingKind.clans, CN, None, None, [_clan(1, "#AAA", "A")])
    await replace_rankings(
        session,
        RankingKind.players,
        CN,
        None,
        None,
        [{"tag": "#P1", "name": "P1", "rank": 1, "trophies": 5000}],
    )

    await replace_rankings(session, RankingKind.clans, CN, None, None, [_clan(2, "#BBB", "B")])

    players_rows = (
        await session.execute(
            select(Ranking.tag).where(Ranking.kind == RankingKind.players)
        )
    ).scalars().all()
    assert players_rows == ["#P1"]


async def test_replace_rankings_keeps_other_season_intact(session):
    """赛季榜按 (league_id, season_id) 隔离。"""
    await replace_rankings(
        session, RankingKind.season_players, None, 48000000, "2026-08",
        [{"tag": "#S1", "name": "S1", "rank": 1}],
    )
    await replace_rankings(
        session, RankingKind.season_players, None, 48000000, "2026-09",
        [{"tag": "#S2", "name": "S2", "rank": 1}],
    )

    await replace_rankings(
        session, RankingKind.season_players, None, 48000000, "2026-09",
        [{"tag": "#S3", "name": "S3", "rank": 1}],
    )

    tags = (
        await session.execute(
            select(Ranking.tag)
            .where(Ranking.kind == RankingKind.season_players)
            .order_by(Ranking.tag)
        )
    ).scalars().all()
    assert tags == ["#S1", "#S3"]


# --------------------------------------------------------------------------- #
# tag 归一化：必须复用 app.coc.tags，不得本地实现
# --------------------------------------------------------------------------- #


async def test_replace_rankings_normalizes_tag_case(session):
    await replace_rankings(
        session, RankingKind.clans, CN, None, None, [_clan(1, "#aaa", "A")]
    )
    tag = (
        await session.execute(select(Ranking.tag).where(Ranking.location_id == CN))
    ).scalar_one()
    assert tag == "#AAA"


async def test_replace_rankings_dedupes_case_insensitive_tags(session):
    """同一份 items 里大小写不同的同一 tag 不能写成两行。

    PostgreSQL 的 UNIQUE 把 NULL 视为互不相等，而地区榜的 ``league_id`` /
    ``season_id`` 恒为 NULL —— 所以 ``UNIQUE(kind, location_id, league_id,
    season_id, tag)`` 在地区榜上**退化成允许重复**。指望存储层兜底是不行的，
    归一化必须在入库前发生：否则 "#AAA" 与 "#aaa" 能共存，榜单上同一个部落占两行。

    保留后出现的那条（它在 items 里更靠后，视为更新的数据）。
    """
    written = await replace_rankings(
        session,
        RankingKind.clans,
        CN,
        None,
        None,
        [_clan(1, "#AAA", "A"), _clan(2, "#aaa", "A 重复")],
    )
    rows = (
        await session.execute(
            select(Ranking.tag, Ranking.rank).where(Ranking.location_id == CN)
        )
    ).all()
    assert rows == [("#AAA", 2)]
    assert written == 1


# --------------------------------------------------------------------------- #
# 各 kind 的字段映射
# --------------------------------------------------------------------------- #


async def test_replace_rankings_maps_clan_fields(session):
    await replace_rankings(
        session,
        RankingKind.clans,
        CN,
        None,
        None,
        [{"tag": "#AAA", "name": "A", "rank": 3, "previousRank": 7,
          "clanLevel": 15, "members": 45, "points": 1234}],
    )
    row = (
        await session.execute(select(Ranking).where(Ranking.location_id == CN))
    ).scalar_one()
    assert row.rank == 3
    assert row.previous_rank == 7
    assert row.members == 45
    assert row.points == 1234


async def test_replace_rankings_maps_player_fields(session):
    await replace_rankings(
        session,
        RankingKind.players,
        CN,
        None,
        None,
        [{"tag": "#P1", "name": "P1", "rank": 1, "previousRank": 0,
          "trophies": 6000, "expLevel": 300, "attackWins": 30, "defenseWins": 12,
          "clanTag": "#AAA", "clanName": "A"}],
    )
    row = (
        await session.execute(select(Ranking).where(Ranking.location_id == CN))
    ).scalar_one()
    assert row.trophies == 6000
    assert row.exp_level == 300
    assert row.attack_wins == 30
    assert row.defense_wins == 12
    assert row.clan_tag == "#AAA"
    assert row.clan_name == "A"


async def test_replace_rankings_maps_capital_without_tag(session):
    """都城榜没有 tag，只有 name —— 必须能存下，且 tag 为 None。"""
    await replace_rankings(
        session,
        RankingKind.capitals,
        CN,
        None,
        None,
        [{"name": "首都", "capitalHallLevel": 12, "trophies": 2500,
          "rank": 1, "previousRank": 2}],
    )
    row = (
        await session.execute(select(Ranking).where(Ranking.location_id == CN))
    ).scalar_one()
    assert row.tag is None
    assert row.name == "首都"


async def test_replace_rankings_maps_builder_base_trophies(session):
    await replace_rankings(
        session,
        RankingKind.players_builder_base,
        CN,
        None,
        None,
        [{"tag": "#P1", "name": "P1", "rank": 1, "builderBaseTrophies": 4200}],
    )
    row = (
        await session.execute(select(Ranking).where(Ranking.location_id == CN))
    ).scalar_one()
    assert row.builder_base_trophies == 4200


async def test_replace_rankings_maps_clan_level_for_builder_base(session):
    await replace_rankings(
        session,
        RankingKind.clans_builder_base,
        CN,
        None,
        None,
        [{"tag": "#AAA", "name": "A", "rank": 1, "clanLevel": 18,
          "builderBaseTrophies": 3000}],
    )
    row = (
        await session.execute(select(Ranking).where(Ranking.location_id == CN))
    ).scalar_one()
    assert row.clan_level == 18
    assert row.builder_base_trophies == 3000


# --------------------------------------------------------------------------- #
# 容错：官方字段缺失 / 类型异常不能炸掉整批
# --------------------------------------------------------------------------- #


async def test_replace_rankings_skips_items_without_rank(session):
    """缺 rank 的条目写不出主键语义，丢掉即可，但不能连带丢掉整批。"""
    written = await replace_rankings(
        session,
        RankingKind.clans,
        CN,
        None,
        None,
        [{"tag": "#AAA", "name": "A"}, _clan(1, "#BBB", "B")],
    )
    assert written == 1


async def test_replace_rankings_tolerates_null_previous_rank(session):
    """新上榜的 previousRank 官方给 null，必须能存。"""
    await replace_rankings(
        session,
        RankingKind.clans,
        CN,
        None,
        None,
        [{"tag": "#AAA", "name": "A", "rank": 1, "previousRank": None}],
    )
    row = (
        await session.execute(select(Ranking).where(Ranking.location_id == CN))
    ).scalar_one()
    assert row.previous_rank is None


async def test_replace_rankings_tolerates_non_dict_items(session):
    """官方偶尔混进非对象元素，不能整批 500。"""
    written = await replace_rankings(
        session,
        RankingKind.clans,
        CN,
        None,
        None,
        [_clan(1, "#AAA", "A"), "垃圾数据", None],
    )
    assert written == 1


async def test_replace_rankings_stamps_fetched_at_as_aware_utc(session):
    await replace_rankings(session, RankingKind.clans, CN, None, None, [_clan(1, "#AAA", "A")])
    row = (
        await session.execute(select(Ranking).where(Ranking.location_id == CN))
    ).scalar_one()
    assert row.fetched_at.tzinfo is not None


async def test_replace_rankings_accepts_v2_season_id(session):
    """赛季榜的 ``season_id`` 也要装得下 ``v2-<ISO>``（23 字符，列宽 64）。"""
    season_id = "v2-2026-09-28T05:00:00Z"
    written = await replace_rankings(
        session,
        RankingKind.season_players,
        None,
        29000022,
        season_id,
        [_clan(1, "#AAA", "A")],
    )
    assert written == 1
    row = (
        await session.execute(select(Ranking).where(Ranking.season_id == season_id))
    ).scalar_one()
    assert row.league_id == 29000022


async def test_replace_rankings_takes_write_lock_before_delete(session):
    """写 rankings 之前必须先拿顾问锁。

    两个采集进程（定时 + 手工 ``collect``）同时 DELETE+INSERT 会互相等锁并
    死锁（2026-10-21 线上 ``DeadlockDetectedError``）。锁必须在 DELETE **之前**
    拿到，否则两边都先把删除做完，再互等对方的插入。
    """
    from app.db.session import engine

    statements: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _capture)
    try:
        await replace_rankings(session, RankingKind.clans, CN, None, None, [])
        await session.commit()
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _capture)

    lock_at = next(
        (i for i, s in enumerate(statements) if "pg_advisory_xact_lock" in s), None
    )
    assert lock_at is not None, f"没有拿写锁，实际语句：{statements}"
    delete_at = next(
        i for i, s in enumerate(statements) if s.lstrip().upper().startswith("DELETE")
    )
    assert lock_at < delete_at


# --------------------------------------------------------------------------- #
# 表约束
# --------------------------------------------------------------------------- #


async def test_ranking_has_no_fk_to_dimension_tables(session):
    """§5.6：业务表不对维表建外键，只建索引。"""
    for fk in Ranking.__table__.foreign_key_constraints:
        raise AssertionError(f"rankings 不应建外键，却有 {fk.elements[0].target_fullname}")


def test_ranking_kind_covers_all_six_kinds():
    assert {k.value for k in RankingKind} == {
        "clans",
        "players",
        "capitals",
        "clans_builder_base",
        "players_builder_base",
        "season_players",
    }


@pytest.mark.parametrize("kind", list(RankingKind))
def test_ranking_kind_is_str_enum(kind):
    """kind 会直接写进库，必须是字符串而不是 ``RankingKind.clans`` 这种 repr。"""
    assert isinstance(kind.value, str)