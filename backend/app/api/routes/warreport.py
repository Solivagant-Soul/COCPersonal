"""War Report：赛季榜与阵容（配兵）接口。

**只读库，绝不回源。** 数据由 ``app.collector.jobs.warreport`` 一天采一次。
与实时榜（``rankings.py``）共用序列化与 meta helper —— 赛季榜和实时榜对前端
必须是同一形状，否则前端得为"看起来一样的榜"写两套解析。

三条契约：

1. **``ttl_seconds`` 是 86400**，不是实时榜的 21600：这两类数据一天才刷一次，
   写着 6 小时会让前端以为"半天前的数据已经该坏了"。
2. **未知快照返回 200 + 空列表**，不是 404 —— 快照每天都在新增，用户手里的旧
   链接不该变成错误；"没采到"和"参数写错"是两件事。
3. **快照校验是两步**：正则只拦形状（``2026-13-99`` 完全符合
   ``^\\d{4}-\\d{2}-\\d{2}$``），日历合法性必须再走 ``date.fromisoformat``，
   否则非法日期会被静默当成"没有这个快照"。

注意本模块与 ``app.warreport``（上游客户端与 mapper）只是同名，**不是**同一个包：
不要在 ``app/`` 下写裸 ``import warreport``。
"""

from __future__ import annotations

import datetime as dt
import re

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.api.routes.rankings import fresh_meta, ranking_out
from app.api.schemas import DEFAULT_PAGE_SIZE, DataOut, clamp_page_size
from app.collector.jobs.warreport import GLOBAL_LOCATION_ID
from app.collector.rankings_service import RankingKind
from app.db.models import Ranking, WarReportArmy

router = APIRouter(prefix="/api/v1")

#: 赛季榜与阵容都是每日采集，meta 的 TTL 与采集周期对齐
_WARREPORT_TTL = 86400

#: 路径参数里的 kind → 库里的 kind。对外只暴露这两个短名：
#: ``wr_season_players`` 是存储细节，不该出现在 URL 里。
_KIND_MAP = {
    "players": RankingKind.wr_season_players,
    "clans": RankingKind.wr_season_clans,
}

#: 赛季列表最多给几季。与采集侧"最近 3 个快照"保持一致。
_MAX_SEASONS = 3

#: 只拦形状，日历合法性另由 ``date.fromisoformat`` 兜（见模块 docstring）
_SNAPSHOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


async def _session():
    from app.db.session import new_session

    return new_session()


def _bad_params(message: str) -> HTTPException:
    """参数不合法 → 400 INVALID_PARAMS（``main.py`` 会转成统一错误体）。"""
    return HTTPException(
        status_code=400, detail={"code": "INVALID_PARAMS", "message": message}
    )


def _validate_snapshot(snapshot: str) -> None:
    if not _SNAPSHOT_RE.match(snapshot):
        raise _bad_params(f"snapshot 必须是 YYYY-MM-DD，收到 {snapshot!r}")
    try:
        dt.date.fromisoformat(snapshot)
    except ValueError as exc:
        raise _bad_params(f"snapshot 不是合法日期: {snapshot!r}") from exc


def _resolve_kind(kind: str) -> RankingKind:
    ranking_kind = _KIND_MAP.get(kind)
    if ranking_kind is None:
        raise _bad_params(f"kind 必须是 {sorted(_KIND_MAP)} 之一")
    return ranking_kind


# --------------------------------------------------------------------------- #
# 赛季列表
# --------------------------------------------------------------------------- #


@router.get("/rankings/warreport/seasons", response_model=None)
async def list_warreport_seasons():
    """最近的赛季快照（最多 3 个，新的在前），带每类榜的条数。"""
    kinds = [str(kind) for kind in _KIND_MAP.values()]
    session = await _session()
    try:
        rows = (
            await session.execute(
                select(
                    Ranking.season_id,
                    Ranking.kind,
                    func.count(),
                    func.max(Ranking.fetched_at),
                )
                # ``location_id`` 必须钉住：``(kind, season_id)`` 并不是唯一 scope。
                # 换 scope 的采集脚本或手工补数一旦写进同一个 kind，条数会翻倍
                # （页面上表现为"这一季怎么多了一倍人"），而且没有任何报错。
                .where(
                    Ranking.kind.in_(kinds),
                    Ranking.location_id == GLOBAL_LOCATION_ID,
                )
                .group_by(Ranking.season_id, Ranking.kind)
            )
        ).all()
    finally:
        await session.close()

    # 两类 kind 各占一行，Python 侧按 season_id 合并成一条
    counts: dict[str, dict[str, int]] = {}
    freshest: dict[str, dt.datetime] = {}
    for season_id, kind, count, fetched_at in rows:
        if season_id is None:  # 这两类 kind 的 season_id 恒有值，兜底而已
            continue
        key = "players" if kind == str(RankingKind.wr_season_players) else "clans"
        counts.setdefault(season_id, {"players": 0, "clans": 0})[key] = count
        if fetched_at is not None and (
            season_id not in freshest or fetched_at > freshest[season_id]
        ):
            freshest[season_id] = fetched_at

    # season_id 是 ISO 日期（YYYY-MM-DD），字典序即时间序
    listed = sorted(counts, reverse=True)[:_MAX_SEASONS]
    items = [
        {
            "seasonId": season_id,
            "players": counts[season_id]["players"],
            "clans": counts[season_id]["clans"],
            "fetchedAt": freshest[season_id].isoformat()
            if season_id in freshest
            else None,
        }
        for season_id in listed
    ]
    # meta 取"列出的这几季"里最新的一次采集
    latest = max((freshest[s] for s in listed if s in freshest), default=None)
    return DataOut(data={"items": items}, meta=fresh_meta(latest, ttl=_WARREPORT_TTL))


# --------------------------------------------------------------------------- #
# 某一季的某一类榜
# --------------------------------------------------------------------------- #


@router.get("/rankings/warreport/seasons/{snapshot}/{kind}", response_model=None)
async def warreport_season_board(
    snapshot: str,
    kind: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1),
):
    """某一快照的玩家榜 / 部落榜。分页规则与实时榜完全一致。

    ``data.kind`` 回路径值（``players`` / ``clans``），不是库里的
    ``wr_season_players`` —— 前端拿到的是它请求的那个名字。
    """
    _validate_snapshot(snapshot)
    ranking_kind = _resolve_kind(kind)

    limit = clamp_page_size(page_size)
    session = await _session()
    try:
        # scope 是（kind, location_id, snapshot）—— 与采集侧写入的 scope 一致。
        # ``(kind, snapshot)`` 不唯一：别的 scope 的行混进来会让 total 变大、
        # 名次串台（``rank`` 在各自 scope 内编号）。
        scope = (
            Ranking.kind == str(ranking_kind),
            Ranking.location_id == GLOBAL_LOCATION_ID,
            Ranking.season_id == snapshot,
        )
        base = select(Ranking).where(*scope)
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
                select(func.max(Ranking.fetched_at)).where(*scope)
            )
        ).scalar_one()
    finally:
        await session.close()

    return DataOut(
        data={
            "items": [ranking_out(r) for r in rows],
            "total": total,
            "kind": kind,
        },
        meta=fresh_meta(latest, ttl=_WARREPORT_TTL),
    )


# --------------------------------------------------------------------------- #
# 阵容（配兵）
# --------------------------------------------------------------------------- #


def _army_out(row: WarReportArmy) -> dict:
    """一条配兵 → 前端形状（camelCase，与榜单一致）。"""
    return {
        "position": row.position,
        "name": row.name,
        "canonicalKey": row.canonical_key,
        "armyShareCode": row.army_share_code,
        "armyLink": row.army_link,
        "playerCount": row.player_count,
        "useCount": row.use_count,
        "percentage": row.percentage,
        "averageStars": row.average_stars,
        "averageDestruction": row.average_destruction,
    }


@router.get("/armies", response_model=None)
async def list_armies():
    """热门配兵，按上游使用率顺序（``position`` 升序）。

    不分页：上游一次只给几十条，整表替换后总量就是最终清单。
    """
    session = await _session()
    try:
        rows = (
            await session.execute(
                select(WarReportArmy).order_by(WarReportArmy.position)
            )
        ).scalars().all()
        latest = (
            await session.execute(select(func.max(WarReportArmy.fetched_at)))
        ).scalar_one()
    finally:
        await session.close()

    return DataOut(
        data={"items": [_army_out(row) for row in rows]},
        meta=fresh_meta(latest, ttl=_WARREPORT_TTL),
    )
