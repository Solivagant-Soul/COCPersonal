"""War Report 原始 JSON → 待入库 dict 的纯函数映射。

两套产出形状，别混：

* :func:`player_item` / :func:`clan_item` 产出**扁平 camelCase 键**，直接喂给
  :func:`app.collector.rankings_service._row_from_item`。那边的 ``_pick`` 只认
  ``clanTag`` / ``clanName`` / ``clanLevel`` 这类扁平键，嵌套的 ``clan`` 对象会
  被静默丢成 NULL（列本来就允许 NULL，不报错）。``fetched_at`` / ``kind`` / scope
  由 ``replace_rankings`` 补 —— 既有分工，这里不重复补。
* :func:`army_row` 产出 ``WarReportArmy`` 的 snake_case **列名**，Task 5 直接
  ``WarReportArmy(**row)``；``fetched_at`` 又是 not null，所以它要 ``now``。

纯函数：不取系统时间、不碰数据库，也不 import FastAPI（``APP_ROLE=collector``
时要能脱离 HTTP 层单独跑）。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from app.coc.tags import normalize_tag

#: ``WarReportArmy.name`` 的列宽。上游的配兵名是人写的标签，超过 100 字符
#: 不是不可能事件；不截断的话 INSERT 会炸掉**整次**整表替换（DELETE 已执行、
#: 事务回滚），阵容就永远停在旧版本 —— 只损失一个名字尾巴要划算得多。
ARMY_NAME_MAX = 100

#: ``WarReportArmy`` 里 not null 的列。缺任何一个都不能成行：把 NULL 放过去，
#: ``WarReportArmy(**row)`` 会在 INSERT 期炸掉整次整表替换（那时 DELETE 已执行、
#: 事务回滚），阵容会永远停在旧版本。丢一条脏行只损失那条配兵。
_ARMY_REQUIRED_COLUMNS = (
    "name",
    "canonical_key",
    "army_share_code",
    "army_link",
    "player_count",
    "use_count",
    "percentage",
    "average_stars",
    "average_destruction",
)


def _str_or_none(value: Any) -> str | None:
    """只收非空字符串。数字不冒充字符串 —— ``name="123"`` 没有意义。"""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _truncate(value: str | None, limit: int) -> str | None:
    """截到列宽以内；``None`` 原样返回（交给必填列检查去丢这一行）。"""
    if value is None:
        return None
    return value[:limit]


def _tag_or_none(value: Any) -> str | None:
    """归一化为 ``#大写``；空值返回 None。

    复用 :func:`app.coc.tags.normalize_tag`，不得自己 ``strip().upper()``。
    ``_row_from_item`` 入库前还会再归一化一次（幂等），这里先做是为了让 mapper
    的输出本身可直接断言、也便于排查采集日志。
    """
    text = _str_or_none(value)
    return normalize_tag(text) if text else None


def _int_or_none(value: Any) -> int | None:
    """接受 ``None`` / ``int`` / 整值 ``float`` / 数字字符串，转不了返回 None。

    ``bool`` 先挡掉：它是 ``int`` 的子类，放过去 ``True`` 会悄悄变成名次 1。

    整值浮点（``3.0``，某些 JSON 序列化会把整数写成这样）按整数收；非整值
    （``3.5``）返回 None —— 名次 3.5 没有意义，丢这一行比编一个名次安全。
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    """接受 ``None`` / ``int`` / ``float`` / 数字字符串，转不了返回 None。

    上游 ``averageStars`` / ``averageDestruction`` 实测有整数形态（``3`` / ``100``），
    整数也必须转成 ``float`` 落 Float 列。
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def player_item(raw: dict[str, Any]) -> dict[str, Any] | None:
    """赛季玩家榜的一条 → ``_row_from_item`` 认得的扁平 item；成不了行返回 None。

    嵌套的 ``clan`` 必须在这里拍平：``clan`` 为 ``null``、缺键或不是对象时，
    ``clanTag`` / ``clanName`` / ``clanLevel`` 三个键都给 None，不抛异常。
    """
    rank = _int_or_none(raw.get("rank"))
    name = _str_or_none(raw.get("name"))
    tag = _tag_or_none(raw.get("tag"))
    if rank is None or not name or not tag:
        return None

    clan = raw.get("clan")
    if not isinstance(clan, dict):
        clan = {}

    return {
        "rank": rank,
        "previousRank": _int_or_none(raw.get("previousRank")),
        "tag": tag,
        "name": name,
        "clanTag": _tag_or_none(clan.get("tag")),
        "clanName": _str_or_none(clan.get("name")),
        "clanLevel": _int_or_none(clan.get("clanLevel")),
        "trophies": _int_or_none(raw.get("trophies")),
        "expLevel": _int_or_none(raw.get("expLevel")),
        "attackWins": _int_or_none(raw.get("attackWins")),
        "defenseWins": _int_or_none(raw.get("defenseWins")),
        # 玩家行没有积分列。显式写 None 而不是省略键：这是「本 kind 没有该字段」
        # 的声明，不是漏写。
        "points": None,
    }


def clan_item(raw: dict[str, Any]) -> dict[str, Any] | None:
    """赛季部落榜的一条 → ``_row_from_item`` 认得的扁平 item；成不了行返回 None。

    上游的部落积分键名是 ``clanPoints``，而榜单列叫 ``points``。
    """
    rank = _int_or_none(raw.get("rank"))
    name = _str_or_none(raw.get("name"))
    tag = _tag_or_none(raw.get("tag"))
    if rank is None or not name or not tag:
        return None

    return {
        "rank": rank,
        "previousRank": _int_or_none(raw.get("previousRank")),
        "tag": tag,
        "name": name,
        "points": _int_or_none(raw.get("clanPoints")),
        "members": _int_or_none(raw.get("members")),
        "clanLevel": _int_or_none(raw.get("clanLevel")),
        # 部落行没有奖杯列（部落的点数是 clanPoints）。显式 None 同上。
        "trophies": None,
    }


def army_row(
    raw: dict[str, Any], position: int, now: dt.datetime
) -> dict[str, Any] | None:
    """``/armies`` 的一条 → ``WarReportArmy`` 的列名 dict；成不了行返回 None。

    ``position`` 由调用方按上游顺序从 1 开始编号（上游不提供序号，顺序即使用率
    降序）。``now`` 原样落 ``fetched_at`` —— mapper 内部绝不取系统时间。
    """
    row = {
        "position": position,
        "name": _truncate(_str_or_none(raw.get("name")), ARMY_NAME_MAX),
        "canonical_key": _str_or_none(raw.get("canonicalKey")),
        "army_share_code": _str_or_none(raw.get("armyShareCode")),
        "army_link": _str_or_none(raw.get("armyLink")),
        "player_count": _int_or_none(raw.get("playerCount")),
        "use_count": _int_or_none(raw.get("useCount")),
        "percentage": _float_or_none(raw.get("percentage")),
        "average_stars": _float_or_none(raw.get("averageStars")),
        "average_destruction": _float_or_none(raw.get("averageDestruction")),
        "fetched_at": now,
    }
    if any(row[column] is None for column in _ARMY_REQUIRED_COLUMNS):
        return None
    return row
