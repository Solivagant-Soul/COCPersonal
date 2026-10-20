"""赛季采集。

**只为「当前赛季」抓排名**。历史赛季只写 ``Season`` 行 —— 否则每次触发都要
扫遍几十年的联赛数据，直接打爆令牌桶。这条是硬约束，不是优化。
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.coc import endpoints as coc
from app.coc.client import CocClient
from app.collector.jobs._upsert import upsert_all
from app.collector.rankings_service import RankingKind, replace_rankings
from app.db.models import Season

logger = logging.getLogger("coc.collector.seasons")

#: 一次只抓多少名次。赛季榜可能上千名，全抓会打爆令牌桶。
_SEASON_PLAYER_LIMIT = 200


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_time(value) -> dt.datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


async def collect_seasons(
    client: CocClient, session: AsyncSession, now: dt.datetime | None = None
) -> dict[str, int]:
    now = now or dt.datetime.now(dt.UTC)
    failures: list[str] = []
    leagues = await coc.get_warleagues(client)
    # 响应形状是 {"items": [...]}（官方；**不是** {"leagues": [...]}）。
    # **不能写成 or []** —— 官方出错时返回 {"error": ...} 这种 dict，
    # 取不到 items 会静默变成"这轮没有联赛"，于是 Season 表不更新而 job 报 success。
    # 取不到就必须当失败。
    league_rows = (leagues or {}).get("items")
    if league_rows is None:
        failures.append(f"warleagues 响应缺少 items 字段: {str(leagues)[:200]}")
        logger.warning("%s", failures[-1])
        await session.commit()
        return {
            "seasons": 0,
            "season_players": 0,
            "items_failed": len(failures),
            "detail": failures[:50],
        }
    league_rows = league_rows or []

    seasons_written = 0
    current_by_league: list[tuple[int, str]] = []

    for league in league_rows:
        league_id = _int(league.get("id"))
        if league_id is None:
            continue
        try:
            payload = await coc.get_league_seasons(client, league_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("seasons %s 采集失败: %s", league_id, exc)
            failures.append(f"seasons/{league_id}: {exc}")
            continue
        rows = []
        for item in (payload or {}).get("seasons") or []:
            season_id = item.get("id")
            if not season_id:
                continue
            rows.append(
                Season(
                    league_id=league_id,
                    id=str(season_id),
                    name=(item.get("name") or str(season_id))[:100],
                    start_time=_parse_time(item.get("startTime")),
                    end_time=_parse_time(item.get("endTime")),
                )
            )
        seasons_written += await upsert_all(session, Season, rows, ["league_id", "id"])

        # 官方按时间倒序返回，第一个就是当前赛季 —— 这是"只为当前赛季抓排名"
        # 得以成立的前提，别改成排序后取最新，官方偶尔会返回过期的第一条。
        if rows:
            current_by_league.append((league_id, rows[0].id))

    await session.commit()

    players_ok = 0
    players_failed = 0
    for league_id, season_id in current_by_league:
        try:
            payload = await coc.get_league_season_players(client, league_id, season_id)
        except Exception as exc:  # noqa: BLE001 - 单个联赛失败不拖垮整轮
            # **必须记账**：只 log 不记账的话，这轮会以 success 收场，
            # 于是"赛季榜没采到"这件事永远没人知道 —— 而赛季榜是查得到的。
            logger.warning("season_players %s/%s 采集失败: %s", league_id, season_id, exc)
            failures.append(f"season_players/{league_id}/{season_id}: {exc}")
            players_failed += 1
            continue
        items = (payload or {}).get("items") or []
        written = await replace_rankings(
            session,
            RankingKind.season_players,
            None,
            league_id,
            season_id,
            items,
            now=now,
        )
        await session.commit()
        players_ok += written

    return {
        "seasons": seasons_written,
        "season_players": players_ok,
        "items_failed": players_failed,
        "detail": failures[:50],
    }
