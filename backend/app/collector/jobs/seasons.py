"""赛季采集（Legend League）。

**只采 Legend League 的赛季榜**，而且**只为「当前赛季」抓排名**：历史赛季只写
``Season`` 行 —— 否则每次触发都要扫遍几十年的数据，直接打爆令牌桶。这两条都是
硬约束，不是优化。

联赛 id 是 ``/leagues`` 里的 Legend League（``29000022``）。另外两套 id 都会 400
（2026-10-21 线上逐个实测）：

- warleague 的 ``48000000``（``/warleagues`` 列表）→ "Unknown value for parameter leagueId"；
- ``/leaguetiers`` 的 ``105000xxx``（Legend I/II/III）→ 同样 Unknown leagueId；
- 同属 ``/leagues`` 的非 Legend 项（如 ``29000020``）→ "Seasons are available only
  for legendary league"。

赛季清单**由旧到新**分页返回（2015-07 起，默认一页 10 条），所以当前赛季要翻到
最后一页，不能取第一条。
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

#: Legend League 在 ``/leagues`` 里的 id。赛季榜**只对 Legend League 开放**，且只认
#: ``/leagues`` 这套 id（``290000xx``）：传 ``/leaguetiers`` 的 ``105000xxx``
#: （Legend I/II/III）会 400 "Unknown value for parameter leagueId"，传 warleague 的
#: ``48000000`` 同样 400 —— 三种都在 2026-10-21 线上实测过。
LEGEND_LEAGUE_ID = 29000022

#: 赛季清单一页最多 50 条；官方**由旧到新**返回（2015-07 起），所以拿当前赛季要翻页。
_SEASON_PAGE_LIMIT = 50

#: 翻页上限（50 × 40 = 2000 个赛季，2015 至今约 135 个）。
#: 必须有上限：游标万一不推进，没有上限就是死循环。
_MAX_SEASON_PAGES = 40

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


async def _fetch_season_items(client: CocClient) -> list[dict]:
    """翻完 Legend League 的赛季清单（官方由旧到新分页返回）。

    取不到 ``items`` 就抛 —— 官方出错时返回 ``{"error": ...}`` 这种 dict，
    静默当"没有赛季"会让 Season 表永不更新而 job 报 success。
    """
    items: list[dict] = []
    seen: set[str] = set()
    after: str | None = None
    for _ in range(_MAX_SEASON_PAGES):
        payload = await coc.get_league_seasons(
            client, LEGEND_LEAGUE_ID, limit=_SEASON_PAGE_LIMIT, after=after
        )
        page = (payload or {}).get("items")
        if page is None:
            raise ValueError(
                f"leagues/{LEGEND_LEAGUE_ID}/seasons 响应缺少 items 字段: "
                f"{str(payload)[:200]}"
            )
        for item in page:
            season_id = item.get("id")
            if season_id and str(season_id) not in seen:
                seen.add(str(season_id))
                items.append(item)
        after = ((payload.get("paging") or {}).get("cursors") or {}).get("after")
        if not after:
            break
    return items


async def collect_seasons(
    client: CocClient, session: AsyncSession, now: dt.datetime | None = None
) -> dict[str, int]:
    now = now or dt.datetime.now(dt.UTC)
    failures: list[str] = []

    try:
        season_items = await _fetch_season_items(client)
    except Exception as exc:  # noqa: BLE001
        # 上游 400（例如拿 tier/warleague 的 id 当联赛 id 传）必须记账成失败。
        failures.append(f"leagues/{LEGEND_LEAGUE_ID}/seasons: {exc}")
        logger.warning("%s", failures[-1])
        await session.commit()
        return _result(0, 0, failures)

    rows: list[Season] = []
    for item in season_items:
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
    # 当前赛季 = id 最大（形如 ``YYYY-MM``，字典序即时间序）。**不要依赖接口顺序**：
    # 官方是由旧到新分页，取第一条会拿到 2015-07。
    if rows:
        season_id = max(rows, key=lambda row: row.id).id
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
