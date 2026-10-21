"""赛季采集（Legend League）。

**只采 Legend League 的赛季榜**，而且**只为「当前赛季」抓排名**：历史赛季只写
``Season`` 行 —— 否则每次触发都要扫遍几十年的数据，直接打爆令牌桶。这两条都是
硬约束，不是优化。

联赛 id 不是 warleague 的 ``48000000``：``/leagues/{leagueId}/seasons`` 只接受
**联赛 tier** 的 id，传 warleague id 会被上游以
``400 Unknown value for parameter leagueId`` 拒绝（2026-10-21 线上实测，
全 23 个 warleague 逐个 400，job 却因为没记账而报 success）。
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

#: Legend League 的**联赛 tier** id。官方只对 Legend League 提供赛季榜
#: （``/leagues/{id}/seasons``），且这个接口只认联赛 tier 的 id —— 传
#: warleague 的 ``48000000`` 一律 400。该值取自社区实现 clashofclans.js 的
#: ``LEGEND_LEAGUE_ID``（生产在用），不是我们自己猜的。
LEGEND_LEAGUE_ID = 105000036

#: 一次抓多少名次。官方默认只给 10 条、``limit`` 上限 50（更多要翻页，一期不做），
#: 所以取满 50 而不是官方默认值 —— 默认值会让赛季榜静默只剩前 10 名。
_SEASON_PLAYER_LIMIT = 50


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

    try:
        payload = await coc.get_league_seasons(client, LEGEND_LEAGUE_ID)
    except Exception as exc:  # noqa: BLE001
        # 上游 400（例如把 warleague id 当联赛 id 传）必须记账成失败。
        failures.append(f"leagues/{LEGEND_LEAGUE_ID}/seasons: {exc}")
        logger.warning("%s", failures[-1])
        await session.commit()
        return _result(0, 0, failures)
    # 响应形状是 {"items": [...]}（官方；**不是** {"seasons": [...]}）。
    # **不能写成 or []** —— 官方出错时返回 {"error": ...} 这种 dict，
    # 取不到 items 会静默变成"这轮没有赛季"，于是 Season 表不更新而 job 报 success。
    # 取不到就必须当失败。
    season_rows = (payload or {}).get("items")
    if season_rows is None:
        failures.append(
            f"leagues/{LEGEND_LEAGUE_ID}/seasons 响应缺少 items 字段: {str(payload)[:200]}"
        )
        logger.warning("%s", failures[-1])
        await session.commit()
        return _result(0, 0, failures)

    rows: list[Season] = []
    for item in season_rows:
        season_id = item.get("id")
        if not season_id:
            continue
        rows.append(
            Season(
                league_id=LEGEND_LEAGUE_ID,
                id=str(season_id),
                name=(item.get("name") or str(season_id))[:100],
                start_time=_parse_time(item.get("startTime")),
                end_time=_parse_time(item.get("endTime")),
            )
        )
    seasons_written = await upsert_all(session, Season, rows, ["league_id", "id"])
    await session.commit()

    players_ok = 0
    # 官方按时间倒序返回，第一个就是当前赛季 —— 这是"只为当前赛季抓排名"
    # 得以成立的前提，别改成排序后取最新，官方偶尔会返回过期的第一条。
    if rows:
        season_id = rows[0].id
        try:
            rankings = await coc.get_league_season_players(
                client, LEGEND_LEAGUE_ID, season_id, limit=_SEASON_PLAYER_LIMIT
            )
        except Exception as exc:  # noqa: BLE001
            # **必须记账**：只 log 不记账的话，这轮会以 success 收场，
            # 于是"赛季榜没采到"这件事永远没人知道 —— 而赛季榜是查得到的。
            logger.warning(
                "season_players %s/%s 采集失败: %s", LEGEND_LEAGUE_ID, season_id, exc
            )
            failures.append(f"season_players/{LEGEND_LEAGUE_ID}/{season_id}: {exc}")
        else:
            items = (rankings or {}).get("items") or []
            players_ok = await replace_rankings(
                session,
                RankingKind.season_players,
                None,
                LEGEND_LEAGUE_ID,
                season_id,
                items,
                now=now,
            )
            await session.commit()

    return _result(seasons_written, players_ok, failures)


def _result(
    seasons_written: int, players_ok: int, failures: list[str]
) -> dict[str, int]:
    """统一返回形状。

    ``items_ok`` / ``items_failed`` 是 ``service._summarize`` 认的字段：**每一项
    失败都要计入 items_failed**（此前只统计了"赛季榜"的失败，联赛列表本身全挂
    也被记成 success —— 线上表现为 ``seasons -> success (ok=0 failed=0)``）。
    """
    return {
        "seasons": seasons_written,
        "season_players": players_ok,
        "items_ok": seasons_written,
        "items_failed": len(failures),
        "detail": failures[:50],
    }
