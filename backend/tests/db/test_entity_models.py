"""实体表与预留表的不变量。

重点（都是 Task 6 的核心设计，不是边角料）：
1. **从属关系有 FK + CASCADE**：删部落实惠及其成员。
2. **业务表对维表不建 FK**：`clans.location_id` / `clan_members.league_tier_id`
   必须是可空、无外键约束的普通列 —— 否则采集顺序一旦颠倒（先落部落后落维表）
   就违反外键。规格 §5.6。
3. 预留表 `users` / `user_clan_subscriptions` 现在就要把唯一约束锁住。
"""

import datetime as dt
from datetime import UTC

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    Clan,
    ClanCapital,
    ClanMember,
    Player,
    User,
    UserClanSubscription,
)


def _now() -> dt.datetime:
    """带时区的 UTC 时间。裸 naive datetime 会让 TTL 判定偏差 8 小时。"""
    return dt.datetime.now(UTC)


# --------------------------------------------------------------------------- #
# 预留表
# --------------------------------------------------------------------------- #


async def test_user_openid_is_unique(session):
    session.add(User(openid="o1", created_at=_now()))
    await session.commit()

    session.add(User(openid="o1", created_at=_now()))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_user_clan_subscription_is_unique_per_pair(session):
    user = User(openid="o1", created_at=_now())
    session.add(user)
    await session.commit()

    session.add(UserClanSubscription(user_id=user.id, clan_tag="#2PP", created_at=_now()))
    await session.commit()

    session.add(UserClanSubscription(user_id=user.id, clan_tag="#2PP", created_at=_now()))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_same_user_can_subscribe_different_clans(session):
    """唯一约束作用在 (user_id, clan_tag) 对上，不是 user_id 单列。"""
    user = User(openid="o1", created_at=_now())
    session.add(user)
    await session.commit()

    session.add_all([
        UserClanSubscription(user_id=user.id, clan_tag="#2PP", created_at=_now()),
        UserClanSubscription(user_id=user.id, clan_tag="#8QU8J9J", created_at=_now()),
    ])
    await session.commit()

    count = len(
        (await session.execute(select(UserClanSubscription))).scalars().all()
    )
    assert count == 2


# --------------------------------------------------------------------------- #
# 从属关系：FK CASCADE
# --------------------------------------------------------------------------- #


async def test_clan_member_cascade_delete(session):
    clan = Clan(tag="#2PP", name="示例", member_count=1, fetched_at=_now())
    session.add(clan)
    session.add(
        ClanMember(
            clan_tag="#2PP",
            player_tag="#9QJ8L0",
            role="leader",
            exp_level=200,
            fetched_at=_now(),
        )
    )
    await session.commit()

    # 删部落，成员必须跟着消失
    await session.execute(delete(Clan).where(Clan.tag == "#2PP"))
    await session.commit()

    remaining = (await session.execute(select(ClanMember))).scalars().all()
    assert remaining == []


async def test_clan_member_has_no_direct_fk_to_players(session):
    """成员表对 players 不建 FK —— 否则成员先落库就会违反约束。"""
    model = ClanMember.__mapper__.local_table
    player_fk = [
        c for c in model.foreign_key_constraints
        if any(str(f.column).startswith("players.") for f in c.elements)
    ]
    assert player_fk == [], "clan_members 不应对 players 建外键"


async def test_clan_capital_is_one_to_one_with_clan(session):
    session.add(Clan(tag="#2PP", name="示例", fetched_at=_now()))
    session.add(
        ClanCapital(
            clan_tag="#2PP",
            capital_hall_level=10,
            districts=[{"id": 7000000, "name": "Capital Peak", "districtHallLevel": 5}],
            fetched_at=_now(),
        )
    )
    await session.commit()

    loaded = await session.get(ClanCapital, "#2PP")
    assert loaded.capital_hall_level == 10
    assert loaded.districts[0]["name"] == "Capital Peak"


async def test_clan_capital_districts_accepts_none(session):
    """官方对无都城部族不发 capital 字段。

    先插 Clan：这正是 FK 约束在起作用的证明 —— 没有部落就不该有都城记录。
    """
    session.add(Clan(tag="#2PP", name="示例", fetched_at=_now()))
    await session.commit()

    session.add(
        ClanCapital(
            clan_tag="#2PP",
            capital_hall_level=0,
            districts=None,
            fetched_at=_now(),
        )
    )
    await session.commit()
    loaded = await session.get(ClanCapital, "#2PP")
    assert loaded.districts is None


async def test_clan_capital_requires_existing_clan(session):
    """FK 约束：没有对应部落就不能插都城记录。"""
    session.add(
        ClanCapital(clan_tag="#NOPE", capital_hall_level=5, fetched_at=_now())
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


# --------------------------------------------------------------------------- #
# 业务表对维表：只建索引，不建 FK
# --------------------------------------------------------------------------- #


async def test_clan_allows_none_location_id(session):
    """location_id 可空且无 FK：维表未落库时部落也能入库。"""
    session.add(Clan(tag="#2PP", name="示例", location_id=None, fetched_at=_now()))
    await session.commit()
    loaded = await session.get(Clan, "#2PP")
    assert loaded.location_id is None


async def test_clan_has_no_fk_to_locations(session):
    model = Clan.__mapper__.local_table
    loc_fk = [
        c for c in model.foreign_key_constraints
        if any(str(f.column).startswith("locations.") for f in c.elements)
    ]
    assert loc_fk == [], "clans 不应对 locations 建外键（规格 §5.6）"


async def test_clan_member_has_no_fk_to_league_tiers(session):
    model = ClanMember.__mapper__.local_table
    fk = [
        c for c in model.foreign_key_constraints
        if any(str(f.column).startswith("league_tiers.") for f in c.elements)
    ]
    assert fk == [], "clan_members 不应对 league_tiers 建外键"


async def test_clan_stores_jsonb_fields(session):
    session.add(
        Clan(
            tag="#2PP",
            name="示例",
            badge_urls={"small": "http://x/s.png"},
            labels=[{"id": 56000000, "name": "Clan Wars"}],
            fetched_at=_now(),
        )
    )
    await session.commit()
    loaded = await session.get(Clan, "#2PP")
    assert loaded.badge_urls["small"] == "http://x/s.png"
    assert loaded.labels[0]["name"] == "Clan Wars"


async def test_clan_member_player_house_is_optional_jsonb(session):
    session.add(Clan(tag="#2PP", name="示例", fetched_at=_now()))
    session.add(
        ClanMember(
            clan_tag="#2PP",
            player_tag="#9QJ8L0",
            player_house=None,
            fetched_at=_now(),
        )
    )
    await session.commit()
    loaded = (
        await session.execute(
            select(ClanMember).where(ClanMember.player_tag == "#9QJ8L0")
        )
    ).scalar_one()
    assert loaded.player_house is None


async def test_player_tag_is_primary_key_and_reverse_lookup_works(session):
    """成员表主键含 player_tag，且已建独立索引支持反查。"""
    table = ClanMember.__mapper__.local_table
    pk_cols = {str(c).split(".")[-1] for c in table.primary_key.columns}
    assert pk_cols == {"clan_tag", "player_tag"}
    assert any(ix.name and "player_tag" in [c.name for c in ix.columns]
               for ix in table.indexes)


async def test_player_optional_fields_accept_none(session):
    """官方对新号不填 legend_statistics / labels。"""
    session.add(
        Player(tag="#9QJ8L0", name="V", exp_level=10, trophies=100, fetched_at=_now())
    )
    await session.commit()
    loaded = await session.get(Player, "#9QJ8L0")
    assert loaded.legend_statistics is None
    assert loaded.labels is None


async def test_player_works_without_clan(session):
    """无部落的玩家：clan_tag / role 必须可空。"""
    session.add(Player(tag="#9QJ8L0", name="V", fetched_at=_now()))
    await session.commit()
    loaded = await session.get(Player, "#9QJ8L0")
    assert loaded.clan_tag is None
    assert loaded.role is None
