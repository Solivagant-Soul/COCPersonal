"""部落与玩家的查询路由。

共同的读路径：``read_through(resource, key, loader, persister, fetcher)``。

- ``loader`` 查库（返回 ORM 或 None）
- ``persister`` 回源成功后落库
- ``fetcher`` 调官方 endpoint，成功返回原始 dict

两个刻意选择（Review Focus 第 4 / 1 条）：

1. **``page_size`` 截断而非 422** —— ``clamp_page_size`` 是全项目唯一截断点。
   官方只接受 1–50，透传会得到 ``badRequest``；让调用方因一个可自动修正的
   参数吃 422 不合理。
2. **非法 tag 返回 400 ``INVALID_TAG`` 而非 422** —— 422 的语义是"参数形状不对"，
   而这里要表达的是"标签不合法"，两者的错误码与前端分支都不同。

``_session`` 的用法注意：``app.db.session.get_session`` 是 ``async_generator``
（为 FastAPI 依赖注入设计），不能 ``async with``，只能用 ``anext`` 取。
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.deps import get_coc_client
from app.api.routes._common import (
    build_meta,
    noop_persist,
    open_session,
    validate_tag,
)
from app.api.errors import coc_error_handler
from app.api.schemas import DEFAULT_PAGE_SIZE, DataOut, MetaOut, clamp_page_size
from app.cache.readthrough import read_through
from app.cache.ttl import get_ttl
from app.coc import endpoints as coc
from app.coc.client import CocClient
from app.coc.errors import CocError
from app.coc.mappers import (
    map_clan,
    map_clan_capital,
    map_clan_members,
    map_clan_war,
    map_cwl_group,
    map_war_logs,
)
from app.coc.tags import normalize_tag
from app.db.models import (
    Clan,
    ClanCapital,
    ClanMember,
    ClanWar,
    ClanWarLog,
    CwlLeagueGroup,
    LeagueTier,
)

router = APIRouter(prefix="/api/v1")

# tag 校验 / session / meta 组装已抽到 ``_common``：``players.py`` 也要用同一份，
# 过去两边各写一份、互相反向 import，直接导致 /players/{tag} 重复注册。


# --------------------------------------------------------------------------- #
# 部落：搜索
# --------------------------------------------------------------------------- #


@router.get("/clans/search", response_model=None)
async def search_clans(
    request: Request,
    name: str | None = Query(default=None),
    location_id: int | None = Query(default=None, alias="locationId"),
    war_frequency: str | None = Query(default=None),
    limit: int | None = Query(default=None),
    client: CocClient = Depends(get_coc_client),
):
    """搜索部落。

    搜索是**无状态**的：没有可缓存的键（同一查询条件也不好归一化），
    所以不走 read_through，直接回源。search 的结果时效性由官方承担。
    """
    if not name and location_id is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_PARAMS",
                "message": "name 与 locationId 至少给一个",
            },
        )

    try:
        data = await coc.search_clans(
            client,
            name=name,
            location_id=location_id,
            war_frequency=war_frequency,
            limit=limit,
        )
    except CocError as exc:
        return await coc_error_handler(request, exc)

    items = data.get("items") or []
    return DataOut(
        data=[_clan_summary(i) for i in items],
        meta=MetaOut(cache="MISS", fetched_at=None, age_seconds=None, ttl_seconds=0),
    )


def _clan_summary(raw: dict) -> dict:
    return {
        "tag": normalize_tag(raw.get("tag") or ""),
        "name": raw.get("name"),
        "clanLevel": raw.get("clanLevel"),
        "members": raw.get("members"),
        "clanPoints": raw.get("clanPoints"),
        "location": raw.get("location"),
        "badgeUrls": raw.get("badgeUrls"),
    }


# --------------------------------------------------------------------------- #
# 部落：详情
# --------------------------------------------------------------------------- #


@router.get("/clans/{tag}", response_model=None)
async def get_clan(
    tag: str,
    request: Request,
    client: CocClient = Depends(get_coc_client),
):
    normalized = validate_tag(tag)
    ttl = get_ttl("clan")

    async def loader():
        session = await open_session()
        try:
            from sqlalchemy import select

            row = (
                await session.execute(select(Clan).where(Clan.tag == normalized))
            ).scalar_one_or_none()
            if row is None:
                return None
            # session 关闭前把需要的值读出来（实例会 detached）
            fetched_at = row.fetched_at
        finally:
            await session.close()
        return {"_row": row, "fetched_at": fetched_at}

    async def fetcher():
        raw = await coc.get_clan(client, normalized)
        now = datetime.now(UTC)
        session = await open_session()
        try:
            from sqlalchemy import delete

            clan = map_clan(raw, now=now)
            capital = map_clan_capital(normalized, raw, now=now)
            members = map_clan_members(clan.tag, raw, now=now)

            await session.merge(clan)
            if capital is not None:
                await session.merge(capital)
            else:
                # 官方不回都城信息时清掉旧记录，别留幽灵数据
                await session.execute(
                    delete(ClanCapital).where(ClanCapital.clan_tag == clan.tag)
                )
            await session.execute(
                delete(ClanMember).where(ClanMember.clan_tag == clan.tag)
            )
            session.add_all(members)
            await session.commit()
        finally:
            await session.close()
        return _clan_out_from_raw(raw, normalized)

    try:
        result = await read_through("clan", normalized, loader, noop_persist, fetcher, None)
    except CocError as exc:
        return await coc_error_handler(request, exc)

    return DataOut(
        data=_clan_out(result.data, normalized),
        meta=build_meta(result.status, result.fetched_at, ttl),
    )


def _clan_out_from_raw(raw: dict, tag: str) -> dict:
    out = dict(raw)
    out["tag"] = normalize_tag(raw.get("tag") or tag)
    return out


def _clan_out(stored: dict, tag: str) -> dict:
    """把 read_through 的结果转成对外 JSON。

    ``stored`` 带 ``_row`` 表示命中了缓存，否则是 fetcher 的原始 dict。
    """
    if "_row" in stored:
        row = stored["_row"]
        return {
            "tag": row.tag,
            "name": row.name,
            "description": row.description,
            "clanLevel": row.clan_level,
            "clanPoints": row.clan_points,
            "clanVersusPoints": row.clan_versus_points,
            "requiredTrophies": row.required_trophies,
            "warFrequency": row.war_frequency,
            "warWinStreak": row.war_win_streak,
            "warWins": row.war_wins,
            "warTies": row.war_ties,
            "warLosses": row.war_losses,
            "isWarLogPublic": row.is_war_log_public,
            "members": row.member_count,
            "location": {"id": row.location_id} if row.location_id else None,
            "badgeUrls": row.badge_urls,
            "labels": row.labels,
        }
    return _clan_out_from_raw(stored, tag)


async def _noop(_data) -> None:
    return None


# --------------------------------------------------------------------------- #
# 部落：成员
# --------------------------------------------------------------------------- #


@router.get("/clans/{tag}/members", response_model=None)
async def get_clan_members(
    tag: str,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1),
    client: CocClient = Depends(get_coc_client),
):
    normalized = validate_tag(tag)
    ttl = get_ttl("clan_members")
    limit = clamp_page_size(page_size)
    offset = (page - 1) * limit

    async def loader():
        """只查该 clan 的成员，不加载整张表——成员表会很大。"""
        from sqlalchemy import func, select

        session = await open_session()
        try:
            total = (
                await session.execute(
                    select(func.count())
                    .select_from(ClanMember)
                    .where(ClanMember.clan_tag == normalized)
                )
            ).scalar_one()
            if total == 0:
                return None
            rows = (
                await session.execute(
                    select(ClanMember)
                    .where(ClanMember.clan_tag == normalized)
                    .order_by(ClanMember.clan_rank)
                    .limit(limit)
                    .offset(offset)
                )
            ).scalars().all()
            items = await _member_items(session, rows)
            fetched_at = rows[0].fetched_at if rows else None
        finally:
            await session.close()
        return {"_items": items, "_fetched_at": fetched_at}

    async def fetcher():
        from sqlalchemy import delete, func, select

        # limit/offset 透传给官方，让它在源头就少传数据（Review Focus 第 4 条：
        # limit 已由 clamp_page_size 截断到 50，官方只接受 1–50）
        raw = await coc.get_clan_members(client, normalized, limit=limit)
        now = datetime.now(UTC)

        session = await open_session()
        try:
            # 官方按 limit 返回的是前 N 名；为了支持任意页，落库时存全量。
            # 这里重新拉一次不带 limit 的成员列表来建库，避免只存半页。
            full = await coc.get_clan_members(client, normalized)
            # 从属关系对 clans 有 FK CASCADE（§5.6），而成员接口的响应里**没有**
            # 部落自身。父行不存在时**绝不补骨架行**：详情页会并发请求
            # ``/clans/{tag}``，骨架行会让那边落库撞主键，用户拿到一份字段全 null
            # 的档案；而且 ``name=tag`` 的假档案一旦命中缓存就再也不会被替换。
            # 此时只在内存里返回本次结果（不落库），下一次请求仍会回源。
            parent = (
                await session.execute(select(Clan).where(Clan.tag == normalized))
            ).scalar_one_or_none()
            if parent is None:
                mapped = map_clan_members(normalized, full, now=now)
                return {
                    "_items": await _member_items(session, mapped[offset : offset + limit]),
                    "_fetched_at": now,
                }

            await session.execute(
                delete(ClanMember).where(ClanMember.clan_tag == normalized)
            )
            session.add_all(map_clan_members(normalized, full, now=now))
            await session.commit()

            rows = (
                await session.execute(
                    select(ClanMember)
                    .where(ClanMember.clan_tag == normalized)
                    .order_by(ClanMember.clan_rank)
                    .limit(limit)
                    .offset(offset)
                )
            ).scalars().all()
            items = await _member_items(session, rows)
        finally:
            await session.close()
        # 落库后重新读，保证分页与缓存一致
        return {"_items": items, "_fetched_at": now}

    try:
        result = await read_through(
            "clan_members", normalized, loader, noop_persist, fetcher, None
        )
    except CocError as exc:
        return await coc_error_handler(request, exc)

    return DataOut(
        data=result.data["_items"],
        meta=build_meta(result.status, result.data.get("_fetched_at"), ttl),
    )


def _member_out(row: ClanMember, league: dict | None = None) -> dict:
    return {
        "tag": row.player_tag,
        "name": row.player_name,
        "role": row.role,
        "expLevel": row.exp_level,
        "townHallLevel": row.town_hall_level,
        "trophies": row.trophies,
        "builderBaseTrophies": row.builder_base_trophies,
        "clanRank": row.clan_rank,
        "previousClanRank": row.previous_clan_rank,
        "donations": row.donations,
        "donationsReceived": row.donations_received,
        "league": league,
    }


async def _member_items(session, rows: list[ClanMember]) -> list[dict]:
    """成员行 → 对外 JSON，顺带补齐联赛名与小图标。

    ``league_tiers`` 是静态维表，本地无 Token 时可能是空的：查不到就给 ``null``，
    前端退化成奖杯数，绝不因为维表没采到就让整个成员接口报错。
    """
    from sqlalchemy import select

    tier_ids = {r.league_tier_id for r in rows if r.league_tier_id is not None}
    leagues: dict[int, dict] = {}
    if tier_ids:
        tiers = (
            await session.execute(select(LeagueTier).where(LeagueTier.id.in_(tier_ids)))
        ).scalars().all()
        leagues = {
            tier.id: {
                "id": tier.id,
                "name": tier.name,
                "iconUrls": tier.icon_urls,
            }
            for tier in tiers
        }
    return [_member_out(row, leagues.get(row.league_tier_id)) for row in rows]



# --------------------------------------------------------------------------- #
# 战场：warlog / currentwar / cwl
#
# 三个路由都**不额外 try/except** CocError —— 业务错误（WarLogPrivate / NotInWar）
# 必须冒泡到 coc_error_handler，绝不走 STALE 降级（Review Focus 第 3 条的负面侧）：
# 降级会让用户看到"这个明显没在战的部落有一份当前战数据"且 API 返回 200。
# --------------------------------------------------------------------------- #


@router.get("/clans/{tag}/warlog", response_model=None)
async def get_clan_warlog(
    tag: str,
    request: Request,
    client: CocClient = Depends(get_coc_client),
):
    normalized = validate_tag(tag)
    ttl = get_ttl("warlog")

    async def loader():
        from sqlalchemy import select

        session = await open_session()
        try:
            rows = (
                await session.execute(
                    select(ClanWarLog)
                    .where(ClanWarLog.clan_tag == normalized)
                    .order_by(ClanWarLog.end_time.desc())
                )
            ).scalars().all()
            if not rows:
                return None
            fetched_at = rows[0].fetched_at
        finally:
            await session.close()
        return {"_items": [_war_log_out(r) for r in rows], "_fetched_at": fetched_at}

    async def fetcher():
        from sqlalchemy import select
        from sqlalchemy.dialects.postgresql import insert

        raw = await coc.get_clan_warlog(client, normalized)
        now = datetime.now(UTC)
        _tag, logs = map_war_logs(normalized, raw, now=now)

        rows_payload = [
            {
                "clan_tag": log.clan_tag,
                "end_time": log.end_time,
                "result": log.result,
                "duration_seconds": log.duration_seconds,
                "clan_score": log.clan_score,
                "opponent_score": log.opponent_score,
                "clan_stars": log.clan_stars,
                "opponent_stars": log.opponent_stars,
                "opponent": log.opponent,
                "attacker": log.attacker,
                "defender": log.defender,
                "stars": log.stars,
                "fetched_at": log.fetched_at,
            }
            for log in logs
        ]

        session = await open_session()
        try:
            await _ensure_clan_row(session, _tag, now)
            # 战报是追加型的：按唯一键 (clan_tag, end_time, result) upsert。
            # **不能用 session.merge** —— 它只认主键 id，而新行 id 是 NULL，
            # 于是每次都插入，库里会膨胀出同一场战斗的几十份副本。
            # 这正是该唯一约束存在的意义：给 upsert 一个可用的冲突目标。
            if rows_payload:
                stmt = insert(ClanWarLog).values(rows_payload)
                await session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=["clan_tag", "end_time", "result"],
                        set_={
                            "duration_seconds": stmt.excluded.duration_seconds,
                            "clan_score": stmt.excluded.clan_score,
                            "opponent_score": stmt.excluded.opponent_score,
                            "clan_stars": stmt.excluded.clan_stars,
                            "opponent_stars": stmt.excluded.opponent_stars,
                            "stars": stmt.excluded.stars,
                            "fetched_at": stmt.excluded.fetched_at,
                        },
                    )
                )
            await session.commit()
            rows = (
                await session.execute(
                    select(ClanWarLog)
                    .where(ClanWarLog.clan_tag == _tag)
                    .order_by(ClanWarLog.end_time.desc())
                )
            ).scalars().all()
            items = [_war_log_out(r) for r in rows]
        finally:
            await session.close()
        return {"_items": items, "_fetched_at": now}

    try:
        result = await read_through("warlog", normalized, loader, noop_persist, fetcher, None)
    except CocError as exc:
        # 业务错误（WarLogPrivate）必须冒泡，绝不走 STALE 降级：
        # 降级会让用户看到一份已失效的战报却拿到 HTTP 200。
        return await coc_error_handler(request, exc)

    return DataOut(
        data={"items": result.data["_items"]},
        meta=build_meta(result.status, result.data.get("_fetched_at"), ttl),
    )


def _war_log_out(row: ClanWarLog) -> dict:
    return {
        "endTime": row.end_time,
        "result": row.result,
        "duration": row.duration_seconds,
        "score": row.clan_score,
        "opponentScore": row.opponent_score,
        "stars": row.stars,
        "opponent": row.opponent,
        "attacker": row.attacker,
        "defender": row.defender,
    }


async def _ensure_clan_row(session, tag: str, now: dt.datetime) -> None:
    """保证父行 ``clans`` 存在。

    战场表对 clans 有 FK CASCADE（§5.6），而 warlog / currentwar / cwl 的响应里
    **都没有部落自身** —— 直接插子行会违反外键。不存在时补一条只有 tag 的骨架行，
    绝不伪造详情字段。
    """
    from sqlalchemy import select

    existing = (
        await session.execute(select(Clan).where(Clan.tag == tag))
    ).scalar_one_or_none()
    if existing is None:
        session.add(Clan(tag=tag, name=tag, fetched_at=now))
        await session.flush()


@router.get("/clans/{tag}/currentwar", response_model=None)
async def get_clan_currentwar(
    tag: str,
    request: Request,
    client: CocClient = Depends(get_coc_client),
):
    normalized = validate_tag(tag)
    ttl = get_ttl("currentwar")

    async def loader():
        from sqlalchemy import select

        session = await open_session()
        try:
            row = (
                await session.execute(
                    select(ClanWar).where(ClanWar.clan_tag == normalized)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            fetched_at = row.fetched_at
        finally:
            await session.close()
        return {"_row": row, "_fetched_at": fetched_at}

    async def fetcher():
        from sqlalchemy import select

        raw = await coc.get_clan_currentwar(client, normalized)
        now = datetime.now(UTC)
        war = map_clan_war(raw, now=now)
        war.clan_tag = normalized

        session = await open_session()
        try:
            await _ensure_clan_row(session, normalized, now)
            await session.merge(war)
            await session.commit()
            row = (
                await session.execute(
                    select(ClanWar).where(ClanWar.clan_tag == normalized)
                )
            ).scalar_one()
        finally:
            await session.close()
        return {"_row": row, "_fetched_at": now}

    try:
        result = await read_through("currentwar", normalized, loader, noop_persist, fetcher, None)
    except CocError as exc:
        return await coc_error_handler(request, exc)

    return DataOut(
        data=_clan_war_out(result.data["_row"]),
        meta=build_meta(result.status, result.data.get("_fetched_at"), ttl),
    )


def _clan_war_out(row: ClanWar) -> dict:
    return {
        "state": row.state,
        "warStartTime": row.war_start_time,
        "warEndTime": row.war_end_time,
        "warDurationSeconds": row.war_duration_seconds,
        "currentScore": row.current_score,
        "totalScore": row.total_score,
        "attack": row.attack,
        "defense": row.defense,
        "attacker": row.attacker,
        "defender": row.defender,
        "opponent": row.opponent,
    }


@router.get("/clans/{tag}/cwl", response_model=None)
async def get_clan_cwl(
    tag: str,
    request: Request,
    client: CocClient = Depends(get_coc_client),
):
    normalized = validate_tag(tag)
    ttl = get_ttl("cwl")

    async def loader():
        from sqlalchemy import select

        session = await open_session()
        try:
            row = (
                await session.execute(
                    select(CwlLeagueGroup).where(CwlLeagueGroup.clan_tag == normalized)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            fetched_at = row.fetched_at
        finally:
            await session.close()
        return {"_row": row, "_fetched_at": fetched_at}

    async def fetcher():
        from sqlalchemy import select

        raw = await coc.get_clan_currentwar_leaguegroup(client, normalized)
        now = datetime.now(UTC)
        group = map_cwl_group(normalized, raw, now=now)

        session = await open_session()
        try:
            await _ensure_clan_row(session, normalized, now)
            await session.merge(group)
            await session.commit()
            row = (
                await session.execute(
                    select(CwlLeagueGroup).where(CwlLeagueGroup.clan_tag == normalized)
                )
            ).scalar_one()
        finally:
            await session.close()
        return {"_row": row, "_fetched_at": now}

    try:
        result = await read_through("cwl", normalized, loader, noop_persist, fetcher, None)
    except CocError as exc:
        return await coc_error_handler(request, exc)

    row = result.data["_row"]
    return DataOut(
        data={
            "currentRound": row.current_round,
            "rounds": row.rounds or [],
        },
        meta=build_meta(result.status, result.data.get("_fetched_at"), ttl),
    )
