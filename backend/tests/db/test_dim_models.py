"""维表 ORM 的读写与不变量。"""

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from app.db.models import Label, League, LeagueTier, Location, Season


async def test_locations_seed_roundtrips(session):
    loc = Location(id=32000000, name="Global", is_country=False, country_code=None)
    session.add(loc)
    await session.commit()
    loaded = await session.get(Location, 32000000)
    assert loaded.name == "Global"
    assert loaded.is_country is False
    assert loaded.country_code is None


async def test_location_country_code_is_optional(session):
    """官方接口在家/国际等无 countryCode 的地区不发该字段。"""
    loc = Location(id=32000001, name="China", is_country=True)
    session.add(loc)
    await session.commit()
    await session.refresh(loc)
    assert loc.country_code is None


async def test_league_tier_stores_icon_urls_as_jsonb(session):
    tier = LeagueTier(id=1, name="Bronze", icon_urls={"small": "http://x/s.png"})
    session.add(tier)
    await session.commit()
    loaded = await session.get(LeagueTier, 1)
    assert loaded.icon_urls["small"] == "http://x/s.png"


async def test_league_kind_distinguishes_three_competitions(session):
    """三种联赛合一，用 kind 区分。"""
    session.add_all([
        League(id=29000000, name="Crystal League I", kind="war"),
        League(id=48000000, name="Crystal League I", kind="capital"),
        League(id=53000000, name="Crystal League I", kind="builder_base"),
    ])
    await session.commit()
    kinds = sorted((await session.execute(select(League.kind))).scalars())
    assert kinds == ["builder_base", "capital", "war"]


async def test_label_kind_distinguishes_clan_and_player(session):
    session.add_all([
        Label(id=1, name="Clan War Lover", kind="clan"),
        Label(id=2, name="Clan War Lover", kind="player"),
    ])
    await session.commit()
    rows = (await session.execute(select(Label))).scalars().all()
    assert {r.kind for r in rows} == {"clan", "player"}


async def test_season_has_composite_primary_key(session):
    """赛季主键为 (league_id, id)；id 形如 '2024-01'。

    用 ORM insert 做第二次插入：若仍走 session.add()，identity map 会在 flush
    前就拦截掉，约束根本到不了数据库，这个测试就成了假测试。
    """
    session.add(Season(league_id=29000000, id="2024-01"))
    await session.commit()

    with pytest.raises(IntegrityError):
        await session.execute(
            insert(Season).values(league_id=29000000, id="2024-01")
        )
        await session.flush()
    await session.rollback()


async def test_same_season_id_allowed_across_leagues(session):
    """同一赛季号在不同联赛下是两条记录。"""
    session.add_all([
        Season(league_id=29000000, id="2024-01"),
        Season(league_id=48000000, id="2024-01"),
    ])
    await session.commit()
    count = len((await session.execute(select(Season))).scalars().all())
    assert count == 2
