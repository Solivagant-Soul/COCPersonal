"""玩家查询路由。

玩家档案的读路径与部落同构。``verifytoken`` 是官方唯一的写语义接口，
但本质只读校验：不落库、不缓存。

打桩目标说明：测试 monkeypatch ``app.api.routes.players`` 上的 ``coc``
函数引用 —— 模块在 import 时绑定了名字，改模块属性就是改路由实际调用的那个。
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import get_coc_client
from app.api.errors import coc_error_handler
from app.api.routes._common import (
    build_meta,
    noop_persist,
    open_session,
    validate_tag,
)
from app.api.schemas import DataOut, MetaOut
from app.cache.readthrough import read_through
from app.cache.ttl import get_ttl
from app.coc import endpoints as coc
from app.coc.client import CocClient
from app.coc.errors import CocError
from app.coc.mappers import map_player
from app.db.models import LeagueTier, Player

router = APIRouter(prefix="/api/v1")


def _int_or_none(value) -> int | None:
    """上游的 id 偶尔是字符串；收敛不了就当没有。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _league_payload(session, row: Player) -> dict | None:
    """联赛（层级）的展示信息：``{id, name, iconUrls}``。

    id 有两个来源：``players.league_tier_id`` 列，或 ``raw_extra`` 里上游原样的
    ``leagueTier`` / ``league`` 对象。**名字与图标优先用上游给的**（回源那次不用
    额外查询），拿不到再查 ``league_tiers`` 维表 —— 那张表由 ``static_data`` 每天
    采一次，缓存命中的请求全靠它。
    """
    extra = row.raw_extra if isinstance(row.raw_extra, dict) else {}
    raw = None
    for key in ("leagueTier", "league"):
        candidate = extra.get(key)
        if isinstance(candidate, dict):
            raw = candidate
            break

    tier_id = _int_or_none(row.league_tier_id)
    if tier_id is None and raw is not None:
        tier_id = _int_or_none(raw.get("id"))
    if tier_id is None:
        return None

    name = raw.get("name") if raw else None
    icons = raw.get("iconUrls") if raw else None
    if not isinstance(name, str) or not isinstance(icons, dict):
        tier = await session.get(LeagueTier, tier_id)
        if tier is not None:
            name = name if isinstance(name, str) else tier.name
            icons = icons if isinstance(icons, dict) else tier.icon_urls

    return {
        "id": tier_id,
        "name": name if isinstance(name, str) else None,
        "iconUrls": icons if isinstance(icons, dict) else None,
    }


def _player_out(stored) -> dict:
    """玩家档案出参。

    ``stored`` 固定是 ``{"_row": Player, "league": dict|None, "fetched_at": ...}``
    —— **缓存命中与回源两条路径形状一致**。早先回源时直接把上游原始 dict 透传，
    结果 ``troops`` 这类字段"第一次查有、TTL 一过就没了"，前端根本没法依赖。

    ``troops`` / ``heroes`` / ``spells`` / ``heroEquipment`` 没有专门的列（上游的
    结构随版本变，落列要频繁迁移），它们躺在 ``raw_extra`` 里，这里原样透出。
    """
    row: Player = stored["_row"]
    extra = row.raw_extra if isinstance(row.raw_extra, dict) else {}
    return {
        "tag": row.tag,
        "name": row.name,
        "expLevel": row.exp_level,
        "trophies": row.trophies,
        "bestTrophies": row.best_trophies,
        "builderBaseTrophies": row.builder_base_trophies,
        "townHallLevel": row.town_hall_level,
        "townHallWeaponLevel": row.town_hall_weapon_level,
        "builderHallLevel": row.builder_hall_level,
        "warStars": row.war_stars,
        "attackWins": row.attack_wins,
        "defenseWins": row.defense_wins,
        "donations": row.donations,
        "donationsReceived": row.donations_received,
        "clan": {"tag": row.clan_tag, "name": row.clan_name} if row.clan_tag else None,
        "role": row.role,
        "league": stored.get("league"),
        "builderBaseLeague": (
            {"id": row.builder_base_league_id} if row.builder_base_league_id else None
        ),
        "achievements": row.achievements,
        "labels": row.labels,
        "legendStatistics": row.legend_statistics,
        "troops": extra.get("troops"),
        "heroes": extra.get("heroes"),
        "spells": extra.get("spells"),
        "heroEquipment": extra.get("heroEquipment"),
    }


@router.get("/players/{tag}", response_model=None)
async def get_player(
    tag: str,
    request: Request,
    client: CocClient = Depends(get_coc_client),
):
    normalized = validate_tag(tag)
    ttl = get_ttl("player")

    async def loader():
        from sqlalchemy import select

        session = await open_session()
        try:
            row = (
                await session.execute(select(Player).where(Player.tag == normalized))
            ).scalar_one_or_none()
            if row is None:
                return None
            league = await _league_payload(session, row)
            fetched_at = row.fetched_at
        finally:
            await session.close()
        return {"_row": row, "league": league, "fetched_at": fetched_at}

    async def fetcher():
        raw = await coc.get_player(client, normalized)
        now = datetime.now(UTC)
        # map_player 返回的是游离对象，commit 不会让它过期，出参可以从它身上取
        row = map_player(raw, now=now)
        session = await open_session()
        try:
            league = await _league_payload(session, row)
            await session.merge(row)
            await session.commit()
        finally:
            await session.close()
        return {"_row": row, "league": league, "fetched_at": now}

    try:
        result = await read_through("player", normalized, loader, noop_persist, fetcher, None)
    except CocError as exc:
        return await coc_error_handler(request, exc)

    return DataOut(
        data=_player_out(result.data),
        meta=build_meta(result.status, result.fetched_at, ttl),
    )


@router.post("/players/{tag}/verifytoken", response_model=None)
async def verify_player_token(
    tag: str,
    request: Request,
    payload: dict,
    client: CocClient = Depends(get_coc_client),
):
    """校验 API token。不落库、不缓存；缺 token 字段时 400。"""
    normalized = validate_tag(tag)
    token = payload.get("token")
    if not token or not isinstance(token, str):
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_PARAMS", "message": "缺少 token 字段"},
        )

    try:
        data = await coc.verify_player_token(client, normalized, token)
    except CocError as exc:
        return await coc_error_handler(request, exc)

    return DataOut(
        data=data,
        meta=MetaOut(cache="MISS", fetched_at=None, age_seconds=None, ttl_seconds=0),
    )
