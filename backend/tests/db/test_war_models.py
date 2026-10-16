"""战场表的不变量。

本批表的核心约束：

1. ``clan_war_logs`` 的 ``UNIQUE(clan_tag, end_time, result)`` —— 防重复写入。
   战报是追加型的，采集会反复拉到同一批，若没有这个约束，库里会迅速膨胀出
   同一场战斗的几十份副本。
2. 从属关系有 FK + CASCADE：删赛季连带删参赛部落。
3. ``clan_wars`` 只存**单边视角**（规格 §5.3）—— 官方 currentwar 只能看到以我方为
   防守方的视角，不拼双边。
"""

import datetime as dt
from datetime import UTC

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    CapitalRaidClan,
    CapitalRaidSeason,
    ClanWar,
    ClanWarLog,
    CwlLeagueGroup,
    CwlWar,
)


def _now() -> dt.datetime:
    return dt.datetime.now(UTC)


@pytest.fixture
async def parent_clan(session):
    """战场表对 clans 有 FK CASCADE（§5.6），故每个用例先备好父部落。"""
    from app.db.models import Clan

    for tag in ("#2PP", "#BBB"):
        session.add(Clan(tag=tag, name=tag, fetched_at=_now()))
    await session.commit()
    yield


# --------------------------------------------------------------------------- #
# clan_wars：单边视角
# --------------------------------------------------------------------------- #


async def test_clan_war_roundtrips_jsonb(session, parent_clan):
    war = ClanWar(
        clan_tag="#2PP",
        state="preparation",
        war_start_time=_now() + dt.timedelta(minutes=30),
        war_end_time=_now() + dt.timedelta(days=1),
        war_duration_seconds=10800,
        current_score=120,
        total_score=310,
        # attack / defense / opponent 都是 JSONB（规格 §5.3）
        attack={"stars": 18, "clanScore": 120},
        defense={"stars": 9, "clanScore": 80},
        opponent={"tag": "#BBB", "name": "对手"},
        fetched_at=_now(),
    )
    session.add(war)
    await session.commit()
    loaded = await session.get(ClanWar, "#2PP")
    assert loaded.state == "preparation"
    assert loaded.current_score == 120
    assert loaded.attack["stars"] == 18
    assert loaded.opponent["name"] == "对手"


async def test_clan_war_is_one_row_per_clan(session, parent_clan):
    """PK 是 clan_tag，重复插入同 tag 应违反主键。"""
    session.add(ClanWar(clan_tag="#2PP", state="preparation", fetched_at=_now()))
    await session.commit()

    session.add(ClanWar(clan_tag="#2PP", state="inBattle", fetched_at=_now()))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


# --------------------------------------------------------------------------- #
# clan_war_logs：唯一约束
# --------------------------------------------------------------------------- #


async def test_war_log_unique_constraint_prevents_duplicates(session, parent_clan):
    """同一 (clan_tag, end_time, result) 只能有一条 —— 防重复写入。"""
    end_time = _now().replace(microsecond=0)
    session.add(
        ClanWarLog(
            clan_tag="#2PP",
            end_time=end_time,
            result="win",
            duration_seconds=10800,
            clan_score=320,
            opponent_score=280,
            fetched_at=_now(),
        )
    )
    await session.commit()

    session.add(
        ClanWarLog(
            clan_tag="#2PP",
            end_time=end_time,
            result="win",
            duration_seconds=10800,
            clan_score=320,
            opponent_score=280,
            fetched_at=_now(),
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_same_end_time_different_result_is_allowed(session, parent_clan):
    """同一时刻不同结果（或同结果不同时刻）都必须能存 —— 约束要够紧也要够松。"""
    end_time = _now().replace(microsecond=0)
    session.add_all([
        ClanWarLog(clan_tag="#2PP", end_time=end_time, result="win", fetched_at=_now()),
        ClanWarLog(clan_tag="#2PP", end_time=end_time, result="lose", fetched_at=_now()),
    ])
    await session.commit()
    count = len((await session.execute(select(ClanWarLog))).scalars().all())
    assert count == 2


async def test_same_clan_can_have_two_logs_at_different_times(session, parent_clan):
    base = _now().replace(microsecond=0)
    session.add_all([
        ClanWarLog(clan_tag="#2PP", end_time=base, result="win", fetched_at=_now()),
        ClanWarLog(
            clan_tag="#2PP",
            end_time=base + dt.timedelta(days=1),
            result="win",
            fetched_at=_now(),
        ),
    ])
    await session.commit()
    assert len((await session.execute(select(ClanWarLog))).scalars().all()) == 2


async def test_two_clans_can_have_same_end_time_and_result(session, parent_clan):
    """clan_tag 在约束里，不能让 A 的战报挡住 B 的。"""
    end_time = _now().replace(microsecond=0)
    session.add_all([
        ClanWarLog(clan_tag="#2PP", end_time=end_time, result="win", fetched_at=_now()),
        ClanWarLog(clan_tag="#BBB", end_time=end_time, result="win", fetched_at=_now()),
    ])
    await session.commit()
    assert len((await session.execute(select(ClanWarLog))).scalars().all()) == 2


async def test_war_log_end_time_is_timestamptz(session, parent_clan):
    """end_time 必须是 TIMESTAMPTZ：naive datetime 会让"最近 24 小时"这类查询偏差 8 小时。"""
    session.add(
        ClanWarLog(clan_tag="#2PP", end_time=_now(), result="win", fetched_at=_now())
    )
    await session.commit()
    loaded = (
        await session.execute(select(ClanWarLog))
    ).scalars().one()
    assert loaded.end_time.tzinfo is not None


# --------------------------------------------------------------------------- #
# CWL
# --------------------------------------------------------------------------- #


async def test_cwl_league_group_stores_rounds_as_jsonb(session, parent_clan):
    group = CwlLeagueGroup(
        clan_tag="#2PP",
        current_round=2,
        rounds=[
            {"round": 1, "war_tags": ["#W1"]},
            {"round": 2, "war_tags": ["#W2"]},
        ],
        fetched_at=_now(),
    )
    session.add(group)
    await session.commit()
    loaded = await session.get(CwlLeagueGroup, "#2PP")
    assert loaded.current_round == 2
    assert len(loaded.rounds) == 2


async def test_cwl_war_pk_is_war_tag(session, parent_clan):
    war = CwlWar(
        war_tag="#W1",
        clan_tag="#2PP",
        opponent_clan_tag="#BBB",
        fetched_at=_now(),
    )
    session.add(war)
    await session.commit()
    loaded = await session.get(CwlWar, "#W1")
    assert loaded.opponent_clan_tag == "#BBB"

    # 用 ORM insert 而非 session.add：后者会被 identity map 在 flush 前拦下，
    # 数据库主键约束根本没被触到，这条断言就成了假测试。
    from sqlalchemy import insert
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await session.execute(
            insert(CwlWar).values(war_tag="#W1", clan_tag="#2PP", fetched_at=_now())
        )
    await session.rollback()


# --------------------------------------------------------------------------- #
# 都城突袭：FK CASCADE
# --------------------------------------------------------------------------- #


async def test_capital_raid_clan_cascade_delete(session, parent_clan):
    """删赛季连带删参赛部落。"""
    # 同上：先落赛季再落部落，让顺序显式
    session.add(CapitalRaidSeason(id=700, season_start=_now(), fetched_at=_now()))
    await session.commit()
    session.add(
        CapitalRaidClan(
            season_id=700, clan_tag="#2PP", offensive_win_count=3, fetched_at=_now()
        )
    )
    await session.commit()

    await session.execute(
        delete(CapitalRaidSeason).where(CapitalRaidSeason.id == 700)
    )
    await session.commit()

    remaining = (await session.execute(select(CapitalRaidClan))).scalars().all()
    assert remaining == []


async def test_capital_raid_clan_requires_existing_season(session):
    """FK 约束：没有赛季就不能有参赛记录。"""
    session.add(
        CapitalRaidClan(season_id=999, clan_tag="#2PP", fetched_at=_now())
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_capital_raid_season_keeps_multiple_clans(session, parent_clan):
    # 显式分两步：先落赛季，再落参赛部落。
    # 混在一个 flush 里时 SQLAlchemy 的插入顺序依赖它自己算表依赖，
    # 而 clan_tag 上并没有 FK（§5.6 只对维表不建，父子间才有），
    # 排序不够直观 —— 分步提交让"先有赛季再有部落"变成显式的。
    session.add(CapitalRaidSeason(id=700, season_start=_now(), fetched_at=_now()))
    await session.commit()
    session.add_all([
        CapitalRaidClan(season_id=700, clan_tag="#2PP", fetched_at=_now()),
        CapitalRaidClan(season_id=700, clan_tag="#BBB", fetched_at=_now()),
    ])
    await session.commit()
    rows = (await session.execute(select(CapitalRaidClan))).scalars().all()
    assert len(rows) == 2


async def test_war_tables_have_no_fk_to_dimension_tables(session):
    """规格 §5.6：业务表不对维表建外键。"""
    for model in (ClanWar, ClanWarLog, CwlLeagueGroup, CwlWar, CapitalRaidSeason):
        table = model.__mapper__.local_table
        for constraint in table.foreign_key_constraints:
            target = constraint.elements[0].target_fullname
            assert not any(
                target.startswith(f"{dim}.")
                for dim in ("locations", "league_tiers", "leagues", "labels", "seasons")
            ), f"{model.__tablename__} 不应对维表 {target} 建外键"