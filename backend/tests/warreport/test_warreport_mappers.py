"""War Report 原始 JSON → 待入库 dict 的纯函数映射。

三条契约要锁住：

1. ``player_item`` / ``clan_item`` 产出的是**扁平 camelCase 键**（``clanTag`` 而不是
   嵌套 ``clan``），且能被 ``rankings_service._row_from_item`` 直接消费 —— 后者的
   键名写错不会报错，只会静默丢字段（列本来就允许 NULL）。
2. ``army_row`` 产出的是 ``WarReportArmy`` 的**snake_case 列名**，``fetched_at``
   取调用方注入的 ``now``（mapper 内部绝不取系统时间）。
3. 脏行返回 ``None`` 让采集跳过该条，而不是让整批失败。
"""

import datetime as dt

from app.collector.rankings_service import RankingKind, _row_from_item
from app.warreport.mappers import army_row, clan_item, player_item

NOW = dt.datetime(2026, 10, 23, 4, 23, tzinfo=dt.UTC)


def _army_raw(**over):
    """一份字段齐全的上游配兵，供各用例按需删/改字段。"""
    raw = {
        "name": "Thrower",
        "canonicalKey": "k1",
        "armyShareCode": "sc",
        "armyLink": "https://link",
        "playerCount": 54,
        "useCount": 332,
        "percentage": 27.27,
        "averageStars": 2.73,
        "averageDestruction": 97.25,
    }
    raw.update(over)
    return raw


# --------------------------------------------------------------------------- #
# 玩家
# --------------------------------------------------------------------------- #


def test_player_item_flattens_nested_clan_and_normalizes_tag():
    raw = {
        "tag": "#2pp", "name": "P1", "rank": 3, "previousRank": 5,
        "expLevel": 300, "trophies": 6000, "attackWins": 30, "defenseWins": 12,
        "clan": {"tag": "#c1", "name": "C1", "clanLevel": 18},
    }
    item = player_item(raw)
    assert item["tag"] == "#2PP"
    assert item["clanTag"] == "#C1"
    assert item["clanName"] == "C1"
    assert item["clanLevel"] == 18
    assert item["trophies"] == 6000
    assert item["points"] is None


def test_player_item_without_clan_is_null_safe():
    item = player_item({"tag": "#P", "name": "P", "rank": 1, "clan": None})
    assert item["clanTag"] is None


def test_player_item_with_missing_clan_key_is_null_safe():
    """上游某些条目干脆没有 ``clan`` 键 —— 缺键与 null 一样，不许 KeyError。"""
    item = player_item({"tag": "#P", "name": "P", "rank": 1})
    assert item["clanTag"] is None
    assert item["clanName"] is None
    assert item["clanLevel"] is None


def test_player_item_accepts_numeric_strings():
    item = player_item(
        {"tag": "#P", "name": "P", "rank": "7", "trophies": "6000", "expLevel": "300"}
    )
    assert item["rank"] == 7
    assert item["trophies"] == 6000
    assert item["expLevel"] == 300


def test_player_item_treats_boolean_rank_as_missing():
    """``bool`` 是 ``int`` 的子类；当数字用会让 ``True`` 变成名次 1。"""
    assert player_item({"tag": "#P", "name": "P", "rank": True}) is None


def test_player_item_output_is_consumable_by_row_from_item():
    """真正的契约：下游 ``_row_from_item`` 认得这些键，不需要再拍平一次。"""
    item = player_item(
        {
            "tag": "#2pp", "name": "P1", "rank": 3, "previousRank": 5,
            "expLevel": 300, "trophies": 6000, "attackWins": 30, "defenseWins": 12,
            "clan": {"tag": "#c1", "name": "C1", "clanLevel": 18},
        }
    )
    row = _row_from_item(
        item, RankingKind.players, 32000000, None, "2026-10-05", NOW
    )
    assert row is not None
    assert row["rank"] == 3
    assert row["previous_rank"] == 5
    assert row["tag"] == "#2PP"
    assert row["clan_tag"] == "#C1"
    assert row["clan_name"] == "C1"
    assert row["clan_level"] == 18
    assert row["trophies"] == 6000
    assert row["exp_level"] == 300
    assert row["attack_wins"] == 30
    assert row["defense_wins"] == 12
    assert row["points"] is None
    assert row["members"] is None


# --------------------------------------------------------------------------- #
# 部落
# --------------------------------------------------------------------------- #


def test_clan_item_maps_clan_points_to_points():
    item = clan_item(
        {"tag": "#C", "name": "C", "rank": 1, "clanPoints": 5000,
         "members": 45, "clanLevel": 15}
    )
    assert item["points"] == 5000
    assert item["members"] == 45
    assert item["trophies"] is None


def test_clan_item_output_is_consumable_by_row_from_item():
    item = clan_item(
        {"tag": "#c", "name": "C", "rank": 2, "previousRank": 4, "clanPoints": "5000",
         "members": 45, "clanLevel": 15}
    )
    row = _row_from_item(item, RankingKind.clans, 32000000, None, "2026-10-05", NOW)
    assert row is not None
    assert row["rank"] == 2
    assert row["previous_rank"] == 4
    assert row["tag"] == "#C"
    assert row["points"] == 5000
    assert row["members"] == 45
    assert row["clan_level"] == 15
    assert row["trophies"] is None
    assert row["clan_tag"] is None


# --------------------------------------------------------------------------- #
# 脏行：跳过该条而不是整批失败
# --------------------------------------------------------------------------- #


def test_mapper_drops_rows_without_rank_or_tag():
    assert player_item({"tag": "#P", "name": "P"}) is None
    assert player_item({"rank": 1, "name": "P"}) is None
    assert clan_item({"rank": 1}) is None


def test_mapper_drops_rows_with_blank_name():
    assert player_item({"tag": "#P", "name": "  ", "rank": 1}) is None
    assert clan_item({"tag": "#C", "name": "", "rank": 1}) is None


# --------------------------------------------------------------------------- #
# 配兵
# --------------------------------------------------------------------------- #


def test_army_row_maps_all_fields():
    row = army_row(_army_raw(), 2, NOW)
    assert row["position"] == 2
    assert row["name"] == "Thrower"
    assert row["canonical_key"] == "k1"
    assert row["army_share_code"] == "sc"
    assert row["army_link"] == "https://link"
    assert row["player_count"] == 54
    assert row["use_count"] == 332
    assert row["percentage"] == 27.27
    assert row["average_stars"] == 2.73
    assert row["average_destruction"] == 97.25
    assert row["fetched_at"] == NOW


def test_army_row_accepts_int_floats():
    """上游 ``averageStars``/``averageDestruction`` 有时是整数（实测有 3 与 100）。"""
    row = army_row(
        {"name": "Balloon", "canonicalKey": "k2", "armyShareCode": "s",
         "armyLink": "https://l", "playerCount": 1, "useCount": 8,
         "percentage": 0.5, "averageStars": 3, "averageDestruction": 100},
        1,
        NOW,
    )
    assert row["average_stars"] == 3.0
    assert row["average_destruction"] == 100.0
    assert isinstance(row["average_stars"], float)


def test_army_row_coerces_numeric_strings():
    row = army_row(
        _army_raw(
            playerCount="54",
            useCount="332",
            percentage="27.27",
            averageStars="2.73",
            averageDestruction="97.25",
        ),
        1,
        NOW,
    )
    assert row["player_count"] == 54
    assert row["use_count"] == 332
    assert row["percentage"] == 27.27
    assert row["average_stars"] == 2.73
    assert row["average_destruction"] == 97.25


def test_army_row_drops_without_canonical_key():
    assert army_row({"name": "X"}, 1, NOW) is None


def test_army_row_drops_rows_missing_a_not_null_column():
    """``warreport_armies`` 的这些列都是 not null。

    放一条 NULL 过去，``WarReportArmy(**row)`` 会在 INSERT 期炸掉整次整表替换 ——
    那时 DELETE 已执行、事务回滚，阵容永远停在旧版本。所以脏行在这里就丢掉。
    """
    for key in (
        "name",
        "canonicalKey",
        "armyShareCode",
        "armyLink",
        "playerCount",
        "useCount",
        "percentage",
        "averageStars",
        "averageDestruction",
    ):
        raw = _army_raw()
        del raw[key]
        assert army_row(raw, 1, NOW) is None, key


def test_army_row_treats_boolean_numbers_as_missing():
    assert army_row(_army_raw(percentage=True), 1, NOW) is None
