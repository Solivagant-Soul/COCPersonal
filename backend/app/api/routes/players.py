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
from app.coc.tags import normalize_tag
from app.db.models import Player

router = APIRouter(prefix="/api/v1")


def _player_out(stored, tag: str) -> dict:
    """玩家档案出参。

    ``stored`` 有两种形态：命中缓存时是 ``{"_row": <Player>, ...}``，回源时是官方原始
    dict。两者字段形状不同，故分开处理。

    这个函数原来住在 ``clans.py`` 里、由 ``players.py`` 反向 import —— 它只有一个主人，
    就该待在主人身边（那处反向 import 直接导致了路由重复注册）。
    """
    if "_row" in stored:
        row = stored["_row"]
        return {
            "tag": row.tag,
            "name": row.name,
            "expLevel": row.exp_level,
            "trophies": row.trophies,
            "bestTrophies": row.best_trophies,
            "builderBaseTrophies": row.builder_base_trophies,
            "townHallLevel": row.town_hall_level,
            "builderHallLevel": row.builder_hall_level,
            "warStars": row.war_stars,
            "attackWins": row.attack_wins,
            "defenseWins": row.defense_wins,
            "clan": {"tag": row.clan_tag, "name": row.clan_name} if row.clan_tag else None,
            "role": row.role,
            "league": {"id": row.league_tier_id} if row.league_tier_id else None,
            "achievements": row.achievements,
            "labels": row.labels,
            "legendStatistics": row.legend_statistics,
        }
    out = dict(stored)
    out["tag"] = normalize_tag(stored.get("tag") or tag)
    return out


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
            fetched_at = row.fetched_at
        finally:
            await session.close()
        return {"_row": row, "fetched_at": fetched_at}

    async def fetcher():
        raw = await coc.get_player(client, normalized)
        now = datetime.now(UTC)
        session = await open_session()
        try:
            await session.merge(map_player(raw, now=now))
            await session.commit()
        finally:
            await session.close()
        return raw

    try:
        result = await read_through("player", normalized, loader, noop_persist, fetcher, None)
    except CocError as exc:
        return await coc_error_handler(request, exc)

    return DataOut(
        data=_player_out(result.data, normalized),
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
