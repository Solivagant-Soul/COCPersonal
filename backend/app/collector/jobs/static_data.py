"""静态维表采集：leaguetiers / locations / labels。

全部走 upsert，**幂等是硬要求** —— 定时任务必然重复跑，任何一次重复都不能让
行数翻倍。

**不建外键**（§5.6）：维表会被整体重导入，业务表只靠 ID 对齐。

``goldpass/seasons/current`` 暂不入库：官方返回的赛季 ID 是整数，而 ``seasons``
表按 ``(league_id, id:str)`` 组织，套进去是错的。一期也没有任何地方消费它，
硬塞只会造出一张没人读、还可能误导的表。要用时再按真实形状建表。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.coc import endpoints as coc
from app.coc.client import CocClient
from app.collector.jobs._upsert import upsert_all
from app.db.models import LABEL_KINDS, Label, LeagueTier, Location


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _name(item: dict[str, Any], limit: int = 100) -> str:
    return (item.get("name") or "")[:limit]


def _icon_urls(item: dict[str, Any]) -> dict | None:
    """图标整体存 JSONB：Supercell 的 small/medium/large 三档结构会变，
    拆成三列就得为每次尺寸调整做一次迁移。

    **字段名是 ``iconUrls``（官方），不是 ``icon``。** 读错键不会报错，只会让
    整张维表的图标列静默变成 NULL —— 2026-10-21 线上核对时发现的一类问题。
    """
    icon = item.get("iconUrls")
    return icon if isinstance(icon, dict) else None


async def collect_static_data(
    client: CocClient, session: AsyncSession, now: dt.datetime | None = None
) -> dict[str, int]:
    """采集静态维表，返回各表写入条数。"""
    now = now or dt.datetime.now(dt.UTC)
    counts: dict[str, int] = {}

    payload = await coc.get_locations(client)
    rows = []
    for item in (payload or {}).get("items") or []:
        lid = _int(item.get("id"))
        if lid is None:
            continue
        rows.append(
            Location(
                id=lid,
                name=_name(item),
                is_country=bool(item.get("isCountry")),
                # Global 等非国家地区官方不发这个字段
                country_code=item.get("countryCode"),
            )
        )
    counts["locations"] = await upsert_all(session, Location, rows, "id")

    tiers = await coc.get_leaguetiers(client)
    tier_rows = []
    # 官方 ``/leaguetiers`` 的响应是 ``{"items": [...]}``（不是 ``tiers``）：
    # 读错键的后果是一行都写不进去，而 job 照样报 success。
    for item in (tiers or {}).get("items") or []:
        tid = _int(item.get("id"))
        if tid is None:
            continue
        tier_rows.append(
            LeagueTier(id=tid, name=_name(item), icon_urls=_icon_urls(item))
        )
    counts["league_tiers"] = await upsert_all(session, LeagueTier, tier_rows, "id")

    counts["clan_labels"] = await _collect_labels(
        session, "clan", await coc.get_clan_labels(client)
    )
    counts["player_labels"] = await _collect_labels(
        session, "player", await coc.get_player_labels(client)
    )

    await session.commit()
    return counts


async def _collect_labels(
    session: AsyncSession, kind: str, payload: dict[str, Any] | None
) -> int:
    assert kind in LABEL_KINDS, f"未知 label kind: {kind}"
    rows = []
    # 官方 ``/labels/clans`` 与 ``/labels/players`` 都返回 ``{"items": [...]}``。
    for item in (payload or {}).get("items") or []:
        lid = _int(item.get("id"))
        if lid is None:
            continue
        rows.append(
            Label(id=lid, kind=kind, name=_name(item), icon_urls=_icon_urls(item))
        )
    return await upsert_all(session, Label, rows, ["id", "kind"])
