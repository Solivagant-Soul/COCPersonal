"""排行榜按 scope 全量替换刷新（§5.4）。

**这里只有一种刷新策略：先 DELETE 该 scope 下全部行，再批量 INSERT，同一事务内完成。**

不要改成逐条 upsert。那样"已掉榜条目永久残留" —— 用户看到的是一份
"半年前的榜单 + 今天的新增"，API 返回 200，没有任何报错提示。这个缺陷
不会让任何普通测试变红，所以 :mod:`tests.db.test_rankings_refresh` 的第一条
测试专门盯它。

模块不 import FastAPI（AGENTS.md 架构边界）：``APP_ROLE=collector`` 时它要能
脱离 HTTP 层单独跑。
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Any

from sqlalchemy import delete, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.coc.tags import normalize_tag
from app.db.models import Ranking


#: 榜单写入的顾问锁 key（``RANK`` 的 ASCII）。**所有**榜单写入都必须先拿这把锁：
#: 定时调度与手工 ``collect`` 是两个进程，两个 ``DELETE + INSERT`` 撞在同一张表上
#: 会互相等锁并最终死锁（2026-10-21 线上真实出现 ``DeadlockDetectedError``）。
#: 它同时兜住另一个坑：都城榜的 ``tag`` 是 NULL，唯一索引认为 NULL 互不相等，
#: ``ON CONFLICT`` 拦不住并发写出的重复行。
#:
#: 用事务级（``_xact_``）：``COMMIT``/``ROLLBACK`` 自动释放，不需要 finally。
#: 因此**调用方必须按 scope 提交**，别把整轮采集包在一个长事务里 —— 否则另一个
#: 采集进程会一直干等这把锁。
_RANKINGS_WRITE_LOCK_KEY = 0x52414E4B


class RankingKind(StrEnum):
    """6 类榜单。

    用 ``StrEnum`` 而非裸字符串：写进库的是 ``kind.value``，既是字符串又能被
    编辑器补全。``StrEnum`` 的成员本身就是 ``str``，所以 ``Ranking.kind ==
    RankingKind.clans`` 与 ``== "clans"`` 等价，查测试里两种写法都能用。
    """

    clans = "clans"
    players = "players"
    capitals = "capitals"
    clans_builder_base = "clans_builder_base"
    players_builder_base = "players_builder_base"
    season_players = "season_players"


#: 各 kind 是否带 tag。都城榜只有 name，没有 tag。
_HAS_TAG = frozenset(
    {
        RankingKind.clans,
        RankingKind.players,
        RankingKind.clans_builder_base,
        RankingKind.players_builder_base,
        RankingKind.season_players,
    }
)


def _int_or_none(value: Any) -> int | None:
    """官方偶尔给 ``null`` 或字符串数字，尽量取整，取不了就 None。

    宁可留空也不要让整批榜单因为一个字段炸掉 —— 一条脏数据不该让整个地区的
    榜单刷不出来。
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _str_or_none(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return text[:limit]


def _pick(item: dict[str, Any], *names: str) -> Any:
    """按候选键名取值。

    Supercell 的响应**混用 camelCase 与 snake_case**：地区部落榜给
    ``previousRank``/``clanLevel``，而内部接口给 ``previous_rank``。写死一种
    会静默丢字段 —— 而且丢得毫无痕迹，因为列本来就允许 NULL。
    """
    for name in names:
        if name in item and item[name] is not None:
            return item[name]
    return None


def _row_from_item(
    item: dict[str, Any],
    kind: RankingKind,
    location_id: int | None,
    league_id: int | None,
    season_id: str | None,
    now: dt.datetime,
) -> dict[str, Any] | None:
    """把一条官方 items 元素转成待入库的 dict；无法成行时返回 None。"""
    rank = _int_or_none(_pick(item, "rank"))
    if rank is None:
        # rank 是必填列，缺了就没法按名次排序，直接丢
        return None

    name = _str_or_none(_pick(item, "name"), 100)
    tag = _str_or_none(_pick(item, "tag"), 10)
    if tag:
        # 必须归一化后再入库：UNIQUE 在地区榜上因 NULL 而失效，
        # "#AAA" 与 "#aaa" 能共存会让同一个部落占两行。
        tag = normalize_tag(tag)
    if not tag and kind in _HAS_TAG:
        return None
    if not name:
        # name 是必填列。都城榜只有 name，没有 tag，所以不能反过来用 tag 兜底。
        return None

    # 玩家榜带的部落信息。clanTag 也要归一化 —— 它会跟 clans 表的 tag 对齐。
    clan_tag_raw = _str_or_none(_pick(item, "clanTag", "clan_tag"), 10)

    return {
        "kind": str(kind),
        "location_id": location_id,
        "league_id": league_id,
        "season_id": season_id,
        "rank": rank,
        "previous_rank": _int_or_none(_pick(item, "previousRank", "previous_rank")),
        "tag": tag,
        "name": name,
        "clan_tag": normalize_tag(clan_tag_raw) if clan_tag_raw else None,
        "clan_name": _str_or_none(_pick(item, "clanName", "clan_name"), 100),
        "clan_level": _int_or_none(_pick(item, "clanLevel", "clan_level")),
        "trophies": _int_or_none(_pick(item, "trophies")),
        "builder_base_trophies": _int_or_none(
            _pick(item, "builderBaseTrophies", "builder_base_trophies")
        ),
        "points": _int_or_none(_pick(item, "points")),
        "members": _int_or_none(_pick(item, "members")),
        "exp_level": _int_or_none(_pick(item, "expLevel", "exp_level")),
        "attack_wins": _int_or_none(_pick(item, "attackWins", "attack_wins")),
        "defense_wins": _int_or_none(_pick(item, "defenseWins", "defense_wins")),
        "fetched_at": now,
    }


async def replace_rankings(
    session: AsyncSession,
    kind: RankingKind,
    location_id: int | None,
    league_id: int | None,
    season_id: str | None,
    items: list[dict[str, Any]],
    now: dt.datetime | None = None,
) -> int:
    """把某个 scope 的榜单整体替换为 ``items``，返回实际写入条数。

    scope 由 ``(kind, location_id, league_id, season_id)`` 四元组确定。同一事务内
    先 ``DELETE`` 该 scope 的全部行再批量 ``INSERT`` —— **不要改成逐条 upsert**。

    ``items`` 为空表示官方返回的榜单确实是空的，此时清空而不是跳过。常见错误实现
    是"空列表就 return"，于是榜单永远停在最后一次非空的那版。

    不 ``commit``：调用方决定事务边界（采集 job 要把多个 scope 放进同一次运行）。
    但**调用方每个 scope 都要尽快 commit**：本函数开头拿的顾问锁是事务级的，
    长事务会把另一个采集进程挡在锁外面。
    """
    now = now or dt.datetime.now(dt.UTC)

    # 先拿写锁再删：并发写 rankings 会死锁（两个进程互等），见 key 的定义。
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": _RANKINGS_WRITE_LOCK_KEY},
    )

    # 先删再插，且 DELETE 用同样的 scope 四元组 —— 少一个条件就会误删别的榜单
    await session.execute(
        delete(Ranking).where(
            Ranking.kind == str(kind),
            Ranking.location_id.is_(None)
            if location_id is None
            else Ranking.location_id == location_id,
            Ranking.league_id.is_(None)
            if league_id is None
            else Ranking.league_id == league_id,
            Ranking.season_id.is_(None)
            if season_id is None
            else Ranking.season_id == season_id,
        )
    )

    rows: list[dict[str, Any]] = []
    # 同一批里可能有大小写不同的同一 tag（归一化后才撞车）。保留**后出现**的那条：
    # 它在 items 里更靠后，视为更新的数据。
    deduped: dict[tuple[str, int | None, int | None, str | None, str | None], dict] = {}
    for item in items:
        if not isinstance(item, dict):
            # 官方偶尔混进非对象元素，跳过而不是整批失败
            continue
        row = _row_from_item(item, kind, location_id, league_id, season_id, now)
        if row is None:
            continue
        key = (row["kind"], row["location_id"], row["league_id"], row["season_id"], row["tag"])
        deduped[key] = row

    rows = list(deduped.values())
    if rows:
        # on_conflict_do_update 只是兜底：正常路径下 DELETE 已经清空了 scope，
        # 不会撞上。但它让本函数在并发下也不会 500。
        stmt = pg_insert(Ranking).values(rows)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=["kind", "location_id", "league_id", "season_id", "tag"],
                set_={k: getattr(stmt.excluded, k) for k in rows[0]},
            )
        )
    return len(rows)