"""官方响应 → ORM 映射器：容错是这里唯一的主角。

三件事必须被锁住，缺一件就是线上故障：

1. **官方随时增删字段**（Review Focus 第 5 条）—— 多一个 `brandNewFieldTomorrow`
   不许炸，少一个 `role` 也不许炸。所有读取一律 `data.get()`。
2. **`fetched_at` 必须等于调用方注入的 `now`，且必须 tz-aware**
   （Review Focus 第 2 条）—— mapper 内部绝不调 `datetime.now()`，
   否则 TTL 判定在非 UTC 服务器上偏差 8 小时。
3. **tag 归一化走 `normalize_tag` 这一处实现**（Review Focus 第 1 条）。
"""

import datetime as dt
import json
from datetime import UTC
from pathlib import Path

from app.coc.mappers import (
    CLAN_TYPES,
    _enum,
    map_clan,
    map_clan_capital,
    map_clan_members,
    map_locations,
    map_player,
)
from app.db.models import Clan, ClanCapital, ClanMember, Player

NOW = dt.datetime(2026, 10, 8, 12, 0, tzinfo=UTC)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# 容错：官方字段增删
# --------------------------------------------------------------------------- #


def test_map_clan_handles_unknown_extra_fields():
    data = {
        "tag": "#2PP",
        "name": "示例",
        "clanLevel": 15,
        "brandNewFieldAppearingTomorrow": {"x": 1},
        "someArrayOfUnknownStuff": [1, 2, 3],
    }
    clan = map_clan(data, now=NOW)
    assert clan.tag == "#2PP"
    assert clan.clan_level == 15


def test_map_clan_survives_bare_minimum_response():
    """只剩 tag + name 也要能映射——官方对某些端点就是只回这些。"""
    clan = map_clan({"tag": "#2PP", "name": "x"}, now=NOW)
    assert clan.tag == "#2PP"
    assert clan.name == "x"
    assert clan.clan_level is None
    # 未提供的嵌套字段不得炸，也不得凭空造值
    assert clan.badge_urls is None
    assert clan.is_war_log_public is None


def test_map_clan_handles_missing_optional_jsonb_fields():
    clan = map_clan({"tag": "#2PP", "name": "x"}, now=NOW)
    assert clan.badge_urls is None
    assert clan.labels is None


def test_map_clan_normalizes_tag_case():
    assert map_clan({"tag": "#2pp", "name": "x"}, now=NOW).tag == "#2PP"
    assert map_clan({"tag": "2pp", "name": "x"}, now=NOW).tag == "#2PP"


def test_map_clan_falls_back_on_unknown_war_frequency():
    """官方未来可能新增 warFrequency 取值，未知值落默认而不是崩。"""
    clan = map_clan({"tag": "#2PP", "warFrequency": "sometimes"}, now=NOW)
    assert clan.war_frequency == "always"


def test_map_clan_type_falls_back_on_unknown_value():
    """未知 type 不得让映射失败；type 本身不落列，只做归一验证。"""
    # 未知 type 不影响其它字段
    clan = map_clan({"tag": "#2PP", "type": "inviteOnly", "clanLevel": 15}, now=NOW)
    assert clan.clan_level == 15

    # 已知取值原样返回
    assert _enum("open", CLAN_TYPES, "open") == "open"
    assert _enum("closed", CLAN_TYPES, "open") == "closed"
    # inviteOnly 也是官方合法值：邀请制部落
    assert _enum("inviteOnly", CLAN_TYPES, "open") == "inviteOnly"
    # 未来可能出现的未知取值落默认
    assert _enum("someFutureType", CLAN_TYPES, "open") == "open"
    assert _enum(None, CLAN_TYPES, "open") == "open"


def test_map_clan_parses_nested_location_without_fk():
    """location 是维表字段：取 id，但不建外键。"""
    clan = map_clan(
        {"tag": "#2PP", "name": "x", "location": {"id": 32000001, "name": "China"}},
        now=NOW,
    )
    assert clan.location_id == 32000001


def test_map_clan_tolerates_null_location():
    clan = map_clan(
        {"tag": "#2PP", "name": "x", "location": None}, now=NOW
    )
    assert clan.location_id is None


def test_map_clan_tolerates_null_war_league():
    clan = map_clan(
        {"tag": "#2PP", "name": "x", "warLeague": None}, now=NOW
    )
    assert clan.war_league_id is None


# --------------------------------------------------------------------------- #
# 都城：可选，不得抛 KeyError
# --------------------------------------------------------------------------- #


def test_map_clan_capital_returns_none_when_absent():
    """搜索接口的响应不含 clanCapital 字段。"""
    assert map_clan_capital("#2PP", {}, now=NOW) is None


def test_map_clan_capital_returns_none_when_null():
    assert map_clan_capital("#2PP", {"clanCapital": None}, now=NOW) is None


def test_map_clan_capital_parses_districts():
    result = map_clan_capital(
        "#2PP",
        {
            "clanCapital": {
                "capitalHallLevel": 10,
                "districts": [
                    {"id": 70000000, "name": "Capital Peak", "districtHallLevel": 10}
                ],
            }
        },
        now=NOW,
    )
    assert result.capital_hall_level == 10
    assert result.districts[0]["name"] == "Capital Peak"


def test_map_clan_capital_handles_missing_districts():
    result = map_clan_capital(
        "#2PP", {"clanCapital": {"capitalHallLevel": 5}}, now=NOW
    )
    assert result.capital_hall_level == 5
    assert result.districts is None


# --------------------------------------------------------------------------- #
# 成员列表
# --------------------------------------------------------------------------- #


def test_map_clan_members_reads_items():
    members = map_clan_members("#2PP", {"items": [_member_fixture()]}, now=NOW)
    assert len(members) == 1
    assert members[0].clan_tag == "#2PP"


def test_map_clan_members_empty_items():
    assert map_clan_members("#2PP", {"items": []}, now=NOW) == []


def test_map_clan_members_tolerates_missing_items():
    """搜索接口的成员列表可能根本不带 items 键。"""
    assert map_clan_members("#2PP", {}, now=NOW) == []


def test_map_clan_members_normalizes_tag():
    members = map_clan_members(
        "#2pp", {"items": [dict(_member_fixture(), tag="#9qj8l0")]}, now=NOW
    )
    assert members[0].clan_tag == "#2PP"
    assert members[0].player_tag == "#9QJ8L0"


def test_map_clan_members_tolerates_missing_role():
    member = _member_fixture()
    member.pop("role", None)
    members = map_clan_members("#2PP", {"items": [member]}, now=NOW)
    assert members[0].role == "member"


def test_map_clan_members_skips_entries_without_tag():
    """条目缺 tag 时无从映射，跳过而不是抛 KeyError。"""
    broken = {k: v for k, v in _member_fixture().items() if k != "tag"}
    assert map_clan_members("#2PP", {"items": [broken]}, now=NOW) == []


def _member_fixture() -> dict:
    return {
        "tag": "#9QJ8L0",
        "name": "Vasilije",
        "role": "leader",
        "expLevel": 205,
        "trophies": 4902,
        "clanRank": 1,
        "previousClanRank": 1,
        "donations": 2268,
        "donationsReceived": 2182,
        "league": {"id": 29000022, "name": "Legend League"},
    }


# --------------------------------------------------------------------------- #
# 玩家
# --------------------------------------------------------------------------- #


def test_map_player_handles_missing_role_when_no_clan():
    data = _load("player_profile.json")
    data.pop("role", None)
    data.pop("clan", None)
    player = map_player(data, now=NOW)
    assert player.role is None
    assert player.clan_tag is None


def test_map_player_normalizes_tag_and_clan_tag():
    player = map_player(
        {"tag": "9qj8l0", "name": "V", "clan": {"tag": "#2pp", "name": "C"}},
        now=NOW,
    )
    assert player.tag == "#9QJ8L0"
    assert player.clan_tag == "#2PP"


def test_map_player_survives_null_clan():
    assert map_player({"tag": "#9QJ8L0", "clan": None}, now=NOW).clan_tag is None


def test_map_player_optional_jsonb_default_to_none():
    player = map_player({"tag": "#9QJ8L0", "name": "V"}, now=NOW)
    assert player.legend_statistics is None
    assert player.achievements is None
    assert player.labels is None


def test_map_player_extracts_league_tier_id():
    player = map_player(
        {"tag": "#9QJ8L0", "league": {"id": 29000022, "name": "Legend League"}},
        now=NOW,
    )
    assert player.league_tier_id == 29000022


# --------------------------------------------------------------------------- #
# 地区
# --------------------------------------------------------------------------- #


def test_map_locations_maps_items():
    items = [
        {"id": 32000000, "name": "Global", "isCountry": False},
        {"id": 32000001, "name": "China", "isCountry": True, "countryCode": "CN"},
    ]
    locs = map_locations(items)
    assert [(l.id, l.name, l.is_country, l.country_code) for l in locs] == [
        (32000000, "Global", False, None),
        (32000001, "China", True, "CN"),
    ]


def test_map_locations_defaults_is_country_false():
    """官方偶发对老地区不发 isCountry。"""
    locs = map_locations([{"id": 32000000, "name": "Global"}])
    assert locs[0].is_country is False


def test_map_locations_empty_list():
    assert map_locations([]) == []


# --------------------------------------------------------------------------- #
# Review Focus 第 2 条：注入的 now 必须原样落在 fetched_at 上，且 tz-aware
# --------------------------------------------------------------------------- #


def test_map_clan_uses_injected_now_with_timezone():
    tz_aware = dt.datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    clan = map_clan({"tag": "#2PP", "name": "x"}, now=tz_aware)
    assert clan.fetched_at == tz_aware
    assert clan.fetched_at.tzinfo is not None


def test_map_player_uses_injected_now():
    player = map_player({"tag": "#9QJ8L0", "name": "V"}, now=NOW)
    assert player.fetched_at == NOW
    assert player.fetched_at.tzinfo is not None


def test_map_clan_members_use_injected_now():
    members = map_clan_members("#2PP", {"items": [_member_fixture()]}, now=NOW)
    assert members[0].fetched_at == NOW


def test_map_clan_capital_uses_injected_now():
    capital = map_clan_capital(
        "#2PP", {"clanCapital": {"capitalHallLevel": 5}}, now=NOW
    )
    assert capital.fetched_at == NOW


def test_mappers_never_call_datetime_now():
    """结构性保证：不得在 mapper 内调用 datetime.now()。

    用 AST 而不是文本搜索：docstring 里为了说明禁止事项必须提到这字样，
    文本搜索迟早误伤——本测试自己就被误伤过一次。
    """
    import ast

    source_path = (
        Path(__file__).resolve().parent.parent.parent / "app" / "coc" / "mappers.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name != "now":
            continue
        base = func.value
        base_name = base.id if isinstance(base, ast.Name) else None
        if base_name in {"datetime", "dt"}:
            offenders.append(f"line {node.lineno}")

    assert not offenders, f"mapper 内部不得取当前时间: {offenders}"


# --------------------------------------------------------------------------- #
# 全字段样本回归：fixtures 里的完整响应必须能整体映射
# --------------------------------------------------------------------------- #


def test_full_clan_fixture_maps():
    clan = map_clan(_load("clan_detail.json"), now=NOW)
    assert isinstance(clan, Clan)
    assert clan.member_count == 44
    assert clan.war_frequency == "always"
    assert clan.location_id == 32000010
    assert clan.capital_league_id == 85000020


def test_full_player_fixture_maps():
    player = map_player(_load("player_profile.json"), now=NOW)
    assert isinstance(player, Player)
    assert player.town_hall_level == 16
    assert player.clan_tag == "#2PP"
    assert player.legend_statistics is not None


def test_full_clan_fixture_capital_and_members_map():
    data = _load("clan_detail.json")
    capital = map_clan_capital("#2PP", data, now=NOW)
    assert isinstance(capital, ClanCapital)
    assert len(capital.districts) == 13

    members = map_clan_members("#2PP", data, now=NOW)
    assert isinstance(members[0], ClanMember)
    # memberList[0] 是会长，[1] 是副会
    assert members[0].player_tag == "#9QJ8L0"
    assert members[1].player_tag == "#8L9P2R"


def test_full_locations_fixture_maps():
    locs = map_locations(_load("locations.json")["items"])
    assert {l.id for l in locs} == {32000000, 32000010, 32000006, 32000001}


def test_full_ranking_fixture_maps_previous_rank_zero():
    """previousRank == 0 表示新上榜，不是 0 号排名。"""
    data = _load("ranking_clans.json")["items"]
    newcomer = [i for i in data if i["previousRank"] == 0][0]
    assert map_clan(newcomer, now=NOW).clan_points == 55088
