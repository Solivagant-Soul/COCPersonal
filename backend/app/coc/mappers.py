"""官方响应 → ORM 映射器。

三条铁律，是本模块存在的全部理由：

1. **所有读取一律 `data.get(key)`，禁止 `data[key]`**（Review Focus 第 5 条）。
   Supercell 随时可能新增字段，也可能对可选字段省略（无部落时 `role` 缺失、
   无都城时 `clanCapital` 缺失）。任何一次 `data[key]` 都是一次线上 500。
   嵌套对象一律 `data.get("location") or {}`。
2. **`now` 由调用方注入，mapper 内部绝不调 `datetime.now()`**
   （Review Focus 第 2 条）。这让 TTL 判定可测，也保证服务器在大陆
   （UTC+8）时不会把 `fetched_at` 记错 8 小时。
3. **tag 归一化只用 `app.coc.tags.normalize_tag`**（Review Focus 第 1 条）。
   别处已有三处自行 `strip().upper()`，每处都漏了 URL 编码。

未知字段一律落到 `raw_extra`（JSONB）而不是丢弃：将来官方加字段时，
后台能看见原始值，加映射只需一次迁移的事后决定。
"""

from __future__ import annotations

import datetime as dt
from datetime import UTC
from typing import Any

from app.coc.tags import normalize_tag
from app.db.models import Clan, ClanCapital, ClanMember, Location, Player

# 酋长战频率。未知值落默认 "always"：官方若新增取值，至少不炸。
WAR_FREQUENCIES = frozenset({"always", "moreThanOncePerWeek", "oncePerWeek",
                             "lessThanOncePerWeek", "never"})
# 部落类型
CLAN_TYPES = frozenset({"open", "inviteOnly", "closed"})
# 玩家职位。未知值落默认 "member"。
PLAYER_ROLES = frozenset({"leader", "coLeader", "admin", "member"})
# 村类型
VILLAGES = frozenset({"home", "builderBase"})

# 已知字段：映射用的白名单。不在其中的字段进 raw_extra。
_CLAN_KNOWN = frozenset({
    "tag", "name", "type", "description", "clanLevel", "clanPoints",
    "clanVersusPoints", "requiredTrophies", "warFrequency", "warWinStreak",
    "warWins", "warTies", "warLosses", "isWarLogPublic", "members",
    "location", "warLeague", "capitalLeague", "requiredBuilderBaseLeague",
    "clanCapital", "chatLanguage", "labels", "badgeUrls", "memberList",
})
#: 玩家已映射字段的白名单。**``league`` / ``leagueTier`` 刻意不在内**：
#: 联赛对象（id + name + iconUrls）要整份留在 ``raw_extra`` 里，缓存命中时才有
#: 名字和图标可用 —— 只存 ``league_tier_id`` 的话，回源那次能显示"传奇联赛 I"，
#: 5 分钟后命中缓存就只剩一个 id，页面上联赛一栏会凭空变空。
_PLAYER_KNOWN = frozenset({
    "tag", "name", "role", "expLevel", "trophies", "bestTrophies",
    "builderBaseTrophies", "requiredTrophies", "warStars", "attackWins",
    "defenseWins", "townHallLevel", "townHallWeaponLevel", "builderHallLevel",
    "builderBaseLeague", "legendStatistics", "clan", "donations",
    "donationsReceived", "achievements", "labels", "versusBattleWins",
    "versusTrophies", "requiredVersusTrophies", "requiredBuilderBaseTrophies",
    "chatLanguage",
})


def _enum(value: str | None, allowed: frozenset[str], default: str) -> str:
    """归一枚举值，未知/缺失一律落 default。

    绝不因未知取值抛异常：官方加一个值不该让我们全线 500。
    """
    if value in allowed:
        return value  # type: ignore[return-value]
    return default


def _int_or_none(value: Any) -> int | None:
    """把可能为 None / 字符串的整数字段收成 int | None。"""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _nested_id(data: dict[str, Any], key: str) -> int | None:
    """取 ``data[key]["id"]``，整个键缺失或为 null 时返回 None。"""
    nested = data.get(key)
    if not isinstance(nested, dict):
        return None
    return _int_or_none(nested.get("id"))


def _extra(data: dict[str, Any], known: frozenset[str]) -> dict[str, Any] | None:
    """收集不在白名单里的字段。全认识时返回 None，别给 JSONB 塞空字典。"""
    extra = {k: v for k, v in data.items() if k not in known}
    return extra or None


# --------------------------------------------------------------------------- #
# 部落
# --------------------------------------------------------------------------- #


def map_clan(data: dict[str, Any], now: dt.datetime) -> Clan:
    """部落详情 → Clan。

    ``clanCapital`` 与 ``memberList`` 不在这里映射：都城走 `map_clan_capital`、
    成员走 `map_clan_members`，一次响应对应三张表。
    """
    tag = normalize_tag(data.get("tag") or "")
    badge_urls = data.get("badgeUrls")
    labels = data.get("labels")

    return Clan(
        tag=tag,
        name=data.get("name") or "",
        description=data.get("description"),
        # type 字段映射到 clan_type；规格未单列该列，故只做归一验证
        clan_level=_int_or_none(data.get("clanLevel")),
        clan_points=_int_or_none(data.get("clanPoints")),
        clan_versus_points=_int_or_none(data.get("clanVersusPoints")),
        required_trophies=_int_or_none(data.get("requiredTrophies")),
        war_frequency=_enum(data.get("warFrequency"), WAR_FREQUENCIES, "always"),
        war_win_streak=_int_or_none(data.get("warWinStreak")),
        war_wins=_int_or_none(data.get("warWins")),
        war_ties=_int_or_none(data.get("warTies")),
        war_losses=_int_or_none(data.get("warLosses")),
        is_war_log_public=data.get("isWarLogPublic"),
        member_count=_int_or_none(data.get("members")),
        location_id=_nested_id(data, "location"),
        war_league_id=_nested_id(data, "warLeague"),
        capital_league_id=_nested_id(data, "capitalLeague"),
        clan_builder_base_league_id=_nested_id(data, "requiredBuilderBaseLeague"),
        chat_language_id=_nested_id(data, "chatLanguage"),
        badge_urls=badge_urls if isinstance(badge_urls, dict) else None,
        labels=labels if isinstance(labels, list) else None,
        raw_extra=_extra(data, _CLAN_KNOWN),
        fetched_at=now,
    )


def map_clan_capital(
    clan_tag: str, data: dict[str, Any], now: dt.datetime
) -> ClanCapital | None:
    """部落都城 → ClanCapital。没有都城字段时返回 None，不得抛 KeyError。

    ``data`` 传整个部落响应即可：这里只挑 ``clanCapital``。
    """
    capital = data.get("clanCapital")
    if not isinstance(capital, dict):
        return None

    districts = capital.get("districts")
    return ClanCapital(
        clan_tag=normalize_tag(clan_tag),
        capital_hall_level=_int_or_none(capital.get("capitalHallLevel")),
        districts=districts if isinstance(districts, list) else None,
        fetched_at=now,
    )


def map_clan_members(
    clan_tag: str, data: dict[str, Any], now: dt.datetime
) -> list[ClanMember]:
    """部落成员列表。

    成员接口与部落详情接口共用同一形状（都有 ``items`` 或 ``memberList``），
    两个键都试一遍，都缺就返回空列表 —— 搜索接口的成员列表可能根本不带这个键。
    条目缺 ``tag`` 时无从映射，跳过而不是抛 KeyError。
    """
    items = data.get("items")
    if items is None:
        items = data.get("memberList")
    if not isinstance(items, list):
        return []

    tag = normalize_tag(clan_tag)
    members: list[ClanMember] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        player_tag = item.get("tag")
        if not player_tag:
            continue
        house = item.get("playerHouse")
        members.append(
            ClanMember(
                clan_tag=tag,
                player_tag=normalize_tag(player_tag),
                player_name=item.get("name"),
                role=_enum(item.get("role"), PLAYER_ROLES, "member"),
                exp_level=_int_or_none(item.get("expLevel")),
                town_hall_level=_int_or_none(item.get("townHallLevel")),
                trophies=_int_or_none(item.get("trophies")),
                builder_base_trophies=_int_or_none(
                    item.get("builderBaseTrophies")
                ),
                required_trophies=_int_or_none(item.get("requiredTrophies")),
                clan_rank=_int_or_none(item.get("clanRank")),
                previous_clan_rank=_int_or_none(item.get("previousClanRank")),
                donations=_int_or_none(item.get("donations")),
                donations_received=_int_or_none(item.get("donationsReceived")),
                league_tier_id=_nested_id(item, "league"),
                builder_base_league_id=_nested_id(item, "builderBaseLeague"),
                player_house=house if isinstance(house, dict) else None,
                fetched_at=now,
            )
        )
    return members


# --------------------------------------------------------------------------- #
# 玩家
# --------------------------------------------------------------------------- #


def map_player(data: dict[str, Any], now: dt.datetime) -> Player:
    """玩家档案 → Player。

    无部落的玩家 ``clan`` 与 ``role`` 都缺失，两者必须可空。
    ``name`` 缺失时给空串：该列 NOT NULL，而官方对封号玩家偶发不发 name。
    """
    clan = data.get("clan")
    achievements = data.get("achievements")
    labels = data.get("labels")
    legend = data.get("legendStatistics")
    # 官方文档在 /players 上写的是 ``leagueTier``，社区实现与我们的老代码用 ``league``。
    # 两个键都认：只认一个的话，另一个世界线里漏掉的那份会让 league_tier_id 恒为
    # NULL —— 页面上的联赛永远是空的，而且不报错、不留痕。
    league = data.get("leagueTier")
    if not isinstance(league, dict):
        league = data.get("league")

    return Player(
        tag=normalize_tag(data.get("tag") or ""),
        name=data.get("name") or "",
        exp_level=_int_or_none(data.get("expLevel")),
        trophies=_int_or_none(data.get("trophies")),
        best_trophies=_int_or_none(data.get("bestTrophies")),
        builder_base_trophies=_int_or_none(data.get("builderBaseTrophies")),
        required_trophies=_int_or_none(data.get("requiredTrophies")),
        war_stars=_int_or_none(data.get("warStars")),
        attack_wins=_int_or_none(data.get("attackWins")),
        defense_wins=_int_or_none(data.get("defenseWins")),
        town_hall_level=_int_or_none(data.get("townHallLevel")),
        town_hall_weapon_level=_int_or_none(data.get("townHallWeaponLevel")),
        builder_hall_level=_int_or_none(data.get("builderHallLevel")),
        versus_battle_wins=_int_or_none(data.get("versusBattleWins")),
        versus_trophies=_int_or_none(data.get("versusTrophies")),
        role=_enum(data.get("role"), PLAYER_ROLES, "member") if data.get("role") else None,
        donations=_int_or_none(data.get("donations")),
        donations_received=_int_or_none(data.get("donationsReceived")),
        clan_tag=normalize_tag(clan["tag"]) if isinstance(clan, dict) and clan.get("tag") else None,
        clan_name=clan.get("name") if isinstance(clan, dict) else None,
        league_tier_id=_int_or_none(league.get("id")) if isinstance(league, dict) else None,
        builder_base_league_id=_nested_id(data, "builderBaseLeague"),
        chat_language_id=_nested_id(data, "chatLanguage"),
        achievements=achievements if isinstance(achievements, list) else None,
        labels=labels if isinstance(labels, list) else None,
        legend_statistics=legend if isinstance(legend, dict) else None,
        raw_extra=_extra(data, _PLAYER_KNOWN),
        fetched_at=now,
    )


# --------------------------------------------------------------------------- #
# 维表
# --------------------------------------------------------------------------- #


def map_locations(items: list[dict[str, Any]]) -> list[Location]:
    """地区列表。``isCountry`` 缺失时落 False（官方对老地区偶发不发）。

    **不收 ``now`` 参数**（R16 裁定）：``locations`` 是维表、没有 ``fetched_at`` 列
    （规格 §5.1 只列四列，Task 3 据此建表）。给它塞时间戳要么改表、要么被静默
    丢弃——后者正是"签名骗人"的典型。维表的 TTL 由 ``cache/ttl.py`` 单独管。
    """
    locs: list[Location] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        loc_id = _int_or_none(item.get("id"))
        if loc_id is None:
            # 没有 id 无法作主键，跳过（维表后续会被 upsert 重新覆盖）
            continue
        locs.append(
            Location(
                id=loc_id,
                name=item.get("name") or "",
                is_country=bool(item.get("isCountry", False)),
                country_code=item.get("countryCode"),
            )
        )
    return locs


# --------------------------------------------------------------------------- #
# 战场（§5.3）
# --------------------------------------------------------------------------- #


def _parse_official_time(value: Any) -> dt.datetime | None:
    """解析官方 ISO8601 时间戳（``2026-10-01T08:30:00.000Z``）为 tz-aware UTC。

    官方一律返回 UTC 的 ``Z`` 后缀。**必须带时区**（Review Focus 第 2 条）：
    存成 naive 会让"最近 24 小时"这类查询在大陆服务器上偏差 8 小时。
    """
    if not value:
        return None
    if isinstance(value, dt.datetime):
        # 已是 datetime；naive 的按 UTC 补上，而不是直接扔掉
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def map_clan_war(data: dict[str, Any], now: dt.datetime):
    """当前战 → ClanWar。整体单边视角（§5.3），不拼双边。"""
    from app.db.models import ClanWar

    return ClanWar(
        clan_tag=normalize_tag(data.get("clan_tag") or ""),
        state=data.get("state"),
        war_start_time=_parse_official_time(data.get("war_start_time")),
        war_end_time=_parse_official_time(data.get("war_end_time")),
        war_duration_seconds=_int_or_none(data.get("war_duration_seconds")),
        current_score=_int_or_none(data.get("current_score")),
        total_score=_int_or_none(data.get("total_score")),
        attack=data.get("attack") if isinstance(data.get("attack"), dict) else None,
        defense=data.get("defense") if isinstance(data.get("defense"), dict) else None,
        attacker=data.get("attacker") if isinstance(data.get("attacker"), dict) else None,
        defender=data.get("defender") if isinstance(data.get("defender"), dict) else None,
        opponent=data.get("opponent") if isinstance(data.get("opponent"), dict) else None,
        fetched_at=now,
    )


def map_war_logs(
    clan_tag: str, data: dict[str, Any], now: dt.datetime
) -> tuple[str, list]:
    """战报列表 → ``(clan_tag, list[ClanWarLog])``。

    官方 warlog 响应里**没有** clan_tag（只有 items），故用入参补上。
    条目缺 ``end_time`` 或 ``result`` 时跳过：唯一约束依赖这两个字段，
    缺了就写不进去。
    """
    from app.db.models import ClanWarLog

    items = data.get("items")
    if not isinstance(items, list):
        items = []
    if not items and isinstance(data.get("clan_tag"), str):
        # 少数情况官方在顶层给 clan_tag 而 items 在别处
        pass

    tag = normalize_tag(clan_tag or data.get("clan_tag") or "")
    logs: list[ClanWarLog] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        end_time = _parse_official_time(item.get("end_time"))
        result = item.get("result")
        if end_time is None or not result:
            continue
        stars = item.get("stars")
        logs.append(
            ClanWarLog(
                clan_tag=tag,
                end_time=end_time,
                result=str(result),
                duration_seconds=_int_or_none(item.get("duration")),
                clan_score=_int_or_none(item.get("score")),
                opponent_score=_int_or_none(item.get("opponentScore")),
                clan_stars=_int_or_none(stars.get("attacker")) if isinstance(stars, dict) else None,
                opponent_stars=_int_or_none(stars.get("defender")) if isinstance(stars, dict) else None,
                opponent=item.get("opponent") if isinstance(item.get("opponent"), dict) else None,
                attacker=item.get("attacker") if isinstance(item.get("attacker"), dict) else None,
                defender=item.get("defender") if isinstance(item.get("defender"), dict) else None,
                stars=stars if isinstance(stars, dict) else None,
                fetched_at=now,
            )
        )
    return tag, logs


def map_cwl_group(clan_tag: str, data: dict[str, Any], now: dt.datetime):
    """CWL 联赛组 → CwlLeagueGroup。"""
    from app.db.models import CwlLeagueGroup

    rounds = data.get("rounds")
    return CwlLeagueGroup(
        clan_tag=normalize_tag(clan_tag or data.get("clan_tag") or ""),
        current_round=_int_or_none(data.get("current_round")),
        rounds=rounds if isinstance(rounds, list) else None,
        fetched_at=now,
    )

# --------------------------------------------------------------------------- #
# 战斗日志
# --------------------------------------------------------------------------- #


def map_battlelog(data: dict[str, Any], *, player_tag: str) -> list[dict[str, Any]]:
    """战斗日志 → 前端直接能渲染的列表。

    **不落库、不建表**：官方只回最近这一批（约一天），没有历史可言。等要做
    「累计采样」时再谈表结构，别让一个只读面板先背上一张表。

    上游有三件不可靠的事，这里逐一兜住：
      1. 时间字段改过名（``timestamp`` → ``battleTimestamp``），两个都读；
      2. 条目可能带 ``attack``（含双方 tag），也可能什么都不带 —— 缺对象时按
         「有没有 ``army``」区分进攻/防守，宁可粗略也不抛异常；
      3. 顺序不保证，按时间倒序自己排。
    """
    items = data.get("items")
    if not isinstance(items, list):
        return []

    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        attack = item.get("attack")
        attack = attack if isinstance(attack, dict) else None
        army = item.get("army")

        kind = _battle_kind(attack, army, player_tag)
        stars = attack.get("stars") if attack else item.get("stars")
        destruction = (
            attack.get("destructionPercentage")
            if attack
            else item.get("destructionPercentage")
        )

        out.append(
            {
                "timestamp": item.get("timestamp") or item.get("battleTimestamp"),
                "kind": kind,
                "stars": _int_or_none(stars),
                "destructionPercentage": _int_or_none(destruction),
                "opponent": _battle_opponent(item, attack, kind),
                "army": _battle_army(army),
            }
        )

    # 时间缺失的排最后（空串比任何 ISO 串都小，配合 reverse 自然沉底）
    out.sort(key=lambda row: row["timestamp"] or "", reverse=True)
    return out


#: 一支队伍里认识的子列表。官方以后加新槽位（如 ``pets`` 之后的）就多一条。
_ARMY_KEYS = ("troops", "spells", "heroes", "pets", "equipment")


def _battle_kind(
    attack: dict[str, Any] | None, army: object, player_tag: str
) -> str:
    """判断这条是「我打的」还是「我被别人打的」。

    有 ``attack`` 时按双方 tag 认（唯一可靠的方式）；没有就退化成
    「带 army 的是进攻」—— 传奇日志里只有进攻条目会附上自己的队伍。
    """
    if attack is not None:
        attacker = _tag_or_none(attack.get("attackerTag"))
        defender = _tag_or_none(attack.get("defenderTag"))
        if attacker:
            return "attack" if attacker == player_tag else "defense"
        if defender:
            return "defense" if defender == player_tag else "attack"
    return "attack" if isinstance(army, dict) else "defense"


def _tag_or_none(value: object) -> str | None:
    """空串先挡掉再归一化 —— ``normalize_tag("")`` 会返回一个只有 ``#`` 的假 tag。"""
    text = value.strip() if isinstance(value, str) else ""
    return normalize_tag(text) if text else None


def _battle_opponent(
    item: dict[str, Any], attack: dict[str, Any] | None, kind: str
) -> dict[str, Any] | None:
    """对手：优先上游给的 ``opponentPlayerTag``，没有就从 attack 的双方里取另一头。"""
    tag = _tag_or_none(item.get("opponentPlayerTag"))
    if not tag and attack is not None:
        other = attack.get("defenderTag") if kind == "attack" else attack.get("attackerTag")
        tag = _tag_or_none(other)
    name = item.get("opponentName")
    name = name if isinstance(name, str) and name else None
    if not tag and name is None:
        return None
    return {"tag": tag, "name": name}


def _battle_army(raw: object) -> dict[str, Any] | None:
    """只留认识的子列表，其余（``shareCode`` 等）不要 —— 前端用不上。"""
    if not isinstance(raw, dict):
        return None
    army = {key: raw[key] for key in _ARMY_KEYS if isinstance(raw.get(key), list)}
    return army or None
