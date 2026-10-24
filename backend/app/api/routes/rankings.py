"""排行榜、地区与数据新鲜度接口。

**这些路由只读库，绝不回源。** 榜单由定时任务（Task 12）写入。若每个用户请求
都触发一次回源，40 个地区 × 6 种榜 × 活跃用户会把 Supercell 令牌桶直接打爆。

所以库里没数据时返回**空列表 + ``meta.cache = "MISS"``**，而不是回源。空列表是
诚实的答案：采集还没跑到这个 scope。

``page_size`` 走 Task 9 建立的 ``clamp_page_size``：超限截断为 50 而非 422
（AGENTS.md 硬规矩）。``page`` 越界返回空列表而非 404。

**只提供全服（Global, 32000000）的部落榜与玩家榜**（2026-10-22 收窄）。
都城榜 / 部落基地榜 / 玩家基地榜的路由与采集一并移除 —— 前端是唯一消费方，
没有外部调用方，保留只会让人以为"还有榜但没数据"。
"""

import datetime as dt
from datetime import UTC

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.schemas import DEFAULT_PAGE_SIZE, DataOut, MetaOut
from app.coc.season_ids import season_sort_key
from app.collector.rankings_service import RankingKind
from app.db.models import CollectorRun, League, Location, Ranking, Season

router = APIRouter(prefix="/api/v1")

#: 全服。官方地区 ID 的高位段是 32000000，Global 是 32000000。
#: **注意 Global 的 ``isCountry`` 是 false** —— 靠 ``is_country`` 过滤找不到它。
DEFAULT_LOCATION_ID = 32000000

#: 每种榜单对应的指标字段。前端按 kind 取，不用猜。
_METRICS_BY_KIND = {
    str(RankingKind.clans): ("points", "members", "clanLevel"),
    str(RankingKind.players): ("trophies", "expLevel", "attackWins", "defenseWins"),
}


async def _session():
    from app.db.session import new_session

    return new_session()


def _clamp(page_size: int) -> int:
    from app.api.schemas import clamp_page_size

    return clamp_page_size(page_size)


def ranking_out(row: Ranking) -> dict:
    """一条榜单 → 前端形状。字段名保持 camelCase，与官方的其余接口一致。

    公开（无下划线）是因为 ``warreport.py`` 也要用：赛季榜与实时榜必须同形状，
    复用同一个序列化函数才能保证「加了一个字段只改一处」。
    """
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


def fresh_meta(fetched_at: dt.datetime | None, ttl: int = 21600) -> MetaOut:
    """统一 meta。``ttl`` 默认是榜单的 6 小时。

    公开（无下划线）是因为 ``warreport.py`` 也复用：赛季榜 / 阵容一天一采，
    调用时传 ``ttl=86400``；默认值保持实时榜的既有行为不变。
    """
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
        ttl_seconds=ttl,
    )


# --------------------------------------------------------------------------- #
# 地区
# --------------------------------------------------------------------------- #


@router.get("/locations", response_model=None)
async def list_locations(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1),
):
    """地区列表。**只返回全服**（Global, 32000000）。

    榜单收窄成只看全服后（2026-10-22），前端不再需要挑地区 —— 保留几十个
    国家选项只会让人以为「榜单是按国家分的」，而实际库里只有全服的数据。

    仍保留分页参数：契约形状不变，前端现有的 ``getLocations()`` 调用不用改。
    """
    session = await _session()
    try:
        stmt = select(Location).where(Location.id == DEFAULT_LOCATION_ID)
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
        meta=fresh_meta(None),
    )


# --------------------------------------------------------------------------- #
# 两类地区榜（部落 / 玩家）
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
                # 名次可能重复（唯一约束键是 tag）：补 tag 让分页顺序确定，
                # 否则同名的两行在 OFFSET 分页下会重复出现或漏掉。
                base.order_by(Ranking.rank, Ranking.tag)
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
        data={
            "items": [ranking_out(r) for r in rows],
            "total": total,
            "kind": str(kind),
        },
        meta=fresh_meta(latest),
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
                base.order_by(Ranking.rank, Ranking.tag)
                .offset((page - 1) * limit)
                .limit(limit)
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
            "items": [ranking_out(r) for r in rows],
            "total": total,
            "leagueId": league_id,
            "seasonId": season_id,
        },
        meta=fresh_meta(latest),
    )


@router.get("/seasons/{league_id}", response_model=None)
async def list_seasons(league_id: int):
    session = await _session()
    try:
        rows = (
            await session.execute(
                select(Season).where(Season.league_id == league_id)
            )
        ).scalars().all()
    finally:
        await session.close()

    # 倒序在 Python 里做，不写成 ``ORDER BY id DESC``：赛季 id 有 ``2026-10`` 与
    # ``v2-2026-09-28T05:00:00Z`` 两种格式，SQL 按字符串排会把 ``v2-`` 永远顶到最前
    # （字母 > 数字），换成旧格式的下一季就排到了末尾。见 ``app.coc.season_ids``。
    rows.sort(key=lambda row: season_sort_key(row.id), reverse=True)

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
        meta=fresh_meta(None),
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
        meta=fresh_meta(None),
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
        meta=fresh_meta(None),
    )