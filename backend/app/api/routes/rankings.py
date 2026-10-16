"""排行榜、地区与数据新鲜度接口。

**这些路由只读库，绝不回源。** 榜单由定时任务（Task 12）写入。若每个用户请求
都触发一次回源，40 个地区 × 6 种榜 × 活跃用户会把 Supercell 令牌桶直接打爆。

所以库里没数据时返回**空列表 + ``meta.cache = "MISS"``**，而不是回源。空列表是
诚实的答案：采集还没跑到这个 scope。

``page_size`` 走 Task 9 建立的 ``clamp_page_size``：超限截断为 50 而非 422
（AGENTS.md 硬规矩）。``page`` 越界返回空列表而非 404。
"""

import datetime as dt
from datetime import UTC

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.schemas import DEFAULT_PAGE_SIZE, DataOut, MetaOut
from app.collector.rankings_service import RankingKind
from app.db.models import CollectorRun, League, Location, Ranking, Season

router = APIRouter(prefix="/api/v1")

#: 中国。官方地区 ID 的高位段是 32000000，中国是 32000001。
DEFAULT_LOCATION_ID = 32000001

#: 每种榜单对应的指标字段。前端按 kind 取，不用猜。
_METRICS_BY_KIND = {
    str(RankingKind.clans): ("points", "members", "clanLevel"),
    str(RankingKind.capitals): ("trophies",),
    str(RankingKind.clans_builder_base): ("points", "members", "clanLevel"),
    str(RankingKind.players): ("trophies", "expLevel", "attackWins", "defenseWins"),
    str(RankingKind.players_builder_base): (
        "trophies",
        "builderBaseTrophies",
        "expLevel",
    ),
}


async def _session():
    from app.db.session import get_session

    return await anext(get_session())


def _clamp(page_size: int) -> int:
    from app.api.schemas import clamp_page_size

    return clamp_page_size(page_size)


def _out(row: Ranking) -> dict:
    """一条榜单 → 前端形状。字段名保持 camelCase，与官方的其余接口一致。"""
    return {
        "rank": row.rank,
        "previousRank": row.previous_rank,
        "tag": row.tag,
        "name": row.name,
        "clanTag": row.clan_tag,
        "clanName": row.clan_name,
        "clanLevel": row.clan_level,
        "trophies": row.trophies,
        "builderBaseTrophies": row.builder_base_trophies,
        "points": row.points,
        "members": row.members,
        "expLevel": row.exp_level,
        "attackWins": row.attack_wins,
        "defenseWins": row.defense_wins,
    }


def _fresh_meta(fetched_at: dt.datetime | None) -> MetaOut:
    age = (
        int((dt.datetime.now(UTC) - fetched_at).total_seconds())
        if fetched_at is not None
        else None
    )
    # 没有数据时 cache 标 MISS —— 榜单由定时任务填充，这里不回源（见模块 docstring）
    return MetaOut(
        cache="MISS" if fetched_at is None else "HIT",
        fetched_at=fetched_at,
        age_seconds=age,
        ttl_seconds=21600,
    )


# --------------------------------------------------------------------------- #
# 地区
# --------------------------------------------------------------------------- #


@router.get("/locations", response_model=None)
async def list_locations(
    country_only: bool = Query(default=True, description="只要国家级地区"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1),
):
    session = await _session()
    try:
        stmt = select(Location)
        if country_only:
            stmt = stmt.where(Location.is_country.is_(True))
        total = (
            await session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        rows = (
            await session.execute(
                stmt.order_by(Location.id)
                .offset((page - 1) * _clamp(page_size))
                .limit(_clamp(page_size))
            )
        ).scalars().all()
    finally:
        await session.close()

    return DataOut(
        data={
            "items": [{"id": r.id, "name": r.name, "countryCode": r.country_code}
                      for r in rows],
            "total": total,
        },
        meta=_fresh_meta(None),
    )


# --------------------------------------------------------------------------- #
# 五类地区榜
# --------------------------------------------------------------------------- #


async def _ranking_page(
    kind: RankingKind,
    location_id: int,
    page: int,
    page_size: int,
):
    limit = _clamp(page_size)
    session = await _session()
    try:
        base = select(Ranking).where(
            Ranking.kind == str(kind), Ranking.location_id == location_id
        )
        total = (
            await session.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        rows = (
            await session.execute(
                base.order_by(Ranking.rank)
                .offset((page - 1) * limit)
                .limit(limit)
            )
        ).scalars().all()
        # fetched_at 取该 scope 最新的一条，用于 meta 的新鲜度
        latest = (
            await session.execute(
                select(func.max(Ranking.fetched_at)).where(
                    Ranking.kind == str(kind), Ranking.location_id == location_id
                )
            )
        ).scalar_one()
    finally:
        await session.close()

    return DataOut(
        data={"items": [_out(r) for r in rows], "total": total, "kind": str(kind)},
        meta=_fresh_meta(latest),
    )


def _make_board_route(path: str, kind: RankingKind, summary: str):
    @router.get(path, response_model=None, summary=summary)
    async def _board(
        locationId: int = Query(default=DEFAULT_LOCATION_ID, description="地区 ID"),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1),
    ):
        return await _ranking_page(kind, locationId, page, page_size)

    # 显式命名：FastAPI 用它生成 OpenAPI operationId，重名会告警
    _board.__name__ = f"list_rankings_{kind.value}"
    return _board


list_rankings_clans = _make_board_route(
    "/rankings/clans", RankingKind.clans, "部落榜"
)
list_rankings_players = _make_board_route(
    "/rankings/players", RankingKind.players, "玩家榜"
)
list_rankings_capitals = _make_board_route(
    "/rankings/capitals", RankingKind.capitals, "都城榜"
)
list_rankings_clans_builder_base = _make_board_route(
    "/rankings/clans_builder_base", RankingKind.clans_builder_base, "部落基地榜"
)
list_rankings_players_builder_base = _make_board_route(
    "/rankings/players_builder_base",
    RankingKind.players_builder_base,
    "玩家基地榜",
)


# --------------------------------------------------------------------------- #
# 赛季榜
# --------------------------------------------------------------------------- #


@router.get("/rankings/season/{league_id}/{season_id}", response_model=None)
async def season_rankings(
    league_id: int,
    season_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1),
):
    limit = _clamp(page_size)
    session = await _session()
    try:
        base = select(Ranking).where(
            Ranking.kind == str(RankingKind.season_players),
            Ranking.league_id == league_id,
            Ranking.season_id == season_id,
        )
        total = (
            await session.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        rows = (
            await session.execute(
                base.order_by(Ranking.rank).offset((page - 1) * limit).limit(limit)
            )
        ).scalars().all()
        latest = (
            await session.execute(
                select(func.max(Ranking.fetched_at)).where(
                    Ranking.kind == str(RankingKind.season_players),
                    Ranking.league_id == league_id,
                    Ranking.season_id == season_id,
                )
            )
        ).scalar_one()
    finally:
        await session.close()

    return DataOut(
        data={
            "items": [_out(r) for r in rows],
            "total": total,
            "leagueId": league_id,
            "seasonId": season_id,
        },
        meta=_fresh_meta(latest),
    )


@router.get("/seasons/{league_id}", response_model=None)
async def list_seasons(league_id: int):
    session = await _session()
    try:
        rows = (
            await session.execute(
                select(Season)
                .where(Season.league_id == league_id)
                .order_by(Season.id.desc())
            )
        ).scalars().all()
    finally:
        await session.close()

    return DataOut(
        data={
            "items": [
                {
                    "id": r.id,
                    "leagueId": r.league_id,
                    "name": r.name,
                    "startTime": r.start_time,
                    "endTime": r.end_time,
                }
                for r in rows
            ]
        },
        meta=_fresh_meta(None),
    )


# --------------------------------------------------------------------------- #
# 联赛
# --------------------------------------------------------------------------- #


@router.get("/leagues/{kind}", response_model=None)
async def list_leagues(
    kind: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1),
):
    """按 kind 取联赛：war / capital / builder_base。"""
    from app.db.models import LEAGUE_KINDS

    if kind not in LEAGUE_KINDS:
        # 非法 kind 是"参数不合法" → 400 INVALID_PARAMS，不是 404：
        # 路径本身存在，是取值域不对
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_PARAMS",
                "message": f"kind 必须是 {LEAGUE_KINDS} 之一",
            },
        )

    limit = _clamp(page_size)
    session = await _session()
    try:
        base = select(League).where(League.kind == kind)
        total = (
            await session.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        rows = (
            await session.execute(
                base.order_by(League.id).offset((page - 1) * limit).limit(limit)
            )
        ).scalars().all()
    finally:
        await session.close()

    return DataOut(
        data={
            "items": [{"id": r.id, "name": r.name, "kind": r.kind} for r in rows],
            "total": total,
        },
        meta=_fresh_meta(None),
    )


# --------------------------------------------------------------------------- #
# 数据新鲜度
# --------------------------------------------------------------------------- #


@router.get("/meta/freshness", response_model=None)
async def meta_freshness():
    """各地区各类榜单的最后采集时间。

    用途是"用户看到旧数据时能告诉他多久没更新"，而不是判健康 —— 判健康用
    ``/readyz``（Task 14）。
    """
    session = await _session()
    try:
        rows = (
            await session.execute(
                select(Ranking.location_id, Ranking.kind, func.max(Ranking.fetched_at))
                .where(Ranking.location_id.is_not(None))
                .group_by(Ranking.location_id, Ranking.kind)
            )
        ).all()

        runs = (
            await session.execute(
                select(
                    CollectorRun.job_name,
                    CollectorRun.status,
                    CollectorRun.finished_at,
                )
                .order_by(CollectorRun.id.desc())
                .limit(20)
            )
        ).all()
    finally:
        await session.close()

    rankings: dict[str, dict[str, str | None]] = {}
    for location_id, kind, fetched_at in rows:
        rankings.setdefault(str(location_id), {})[str(kind)] = (
            fetched_at.isoformat() if fetched_at is not None else None
        )

    return DataOut(
        data={
            "rankings": rankings,
            "collectorRuns": [
                {"jobName": j, "status": s, "finishedAt": f}
                for j, s, f in runs
            ],
        },
        meta=_fresh_meta(None),
    )