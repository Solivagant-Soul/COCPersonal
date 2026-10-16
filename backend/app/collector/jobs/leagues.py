"""联赛维表采集：war / capital / builder base 三类联赛。

维表会被整体重导入，所以走 upsert 而非全量替换 —— 全量替换会在官方临时
少返回一类联赛时把整表清空。
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from app.coc import endpoints as coc
from app.coc.client import CocClient
from app.collector.jobs._upsert import upsert_all
from app.db.models import LEAGUE_KINDS, League


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def collect_leagues(
    client: CocClient, session: AsyncSession, now: dt.datetime | None = None
) -> dict[str, int]:
    now = now or dt.datetime.now(dt.UTC)
    counts: dict[str, int] = {}

    for kind, fetch in (
        (LEAGUE_KINDS[0], coc.get_warleagues),
        (LEAGUE_KINDS[1], coc.get_capitalleagues),
        (LEAGUE_KINDS[2], coc.get_builderbaseleagues),
    ):
        payload = await fetch(client)
        rows = []
        for item in (payload or {}).get("leagues") or []:
            lid = _int(item.get("id"))
            if lid is None:
                continue
            rows.append(
                League(
                    id=lid,
                    kind=str(kind),
                    name=(item.get("name") or "")[:100],
                    icon_urls=item.get("icon") if isinstance(item.get("icon"), dict) else None,
                )
            )
        counts[str(kind)] = await upsert_all(session, League, rows, ["id", "kind"])

    await session.commit()
    return counts
