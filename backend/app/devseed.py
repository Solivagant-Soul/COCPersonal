"""开发期种子数据：把 ``app/coc/fixtures/`` 的样本灌进库。

没有真实 Supercell Token 时，排行榜接口读的是**数据库**而不是实时上游，
所以本地联调前先跑一次这个，排行榜页才有东西可显示。

**仅用于开发与演示**，不进生产数据流程。真实采集走 ``app/collector/``。
夹具随包分发（``app/coc/fixtures/``），所以这个命令在**部署后的容器里也能跑**。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.collector.jobs._upsert import upsert_all
from app.collector.rankings_service import RankingKind, replace_rankings
from app.coc.devfixtures import FIXTURES_DIR
from app.db.models import Location

#: 夹具目录：**与夹具上游共用同一个定义**（``app/coc/devfixtures.py``）。
#: 自己算路径就是当初的坑：仓库相对路径在生产镜像里不存在 → seed 命令在镜像里
#: ``FileNotFoundError``。夹具是**运行时资产**（夹具上游要读它），必须随包分发。
#:
#: 榜单地区是**全服**（32000000）—— 与采集 job 与 API 的默认地区一致
#: （2026-10-22 收窄）。原先这里是中国 32000001，于是夹具模式下「榜上有数据、
#: 但榜单页查不出来」—— 页面上地区显示成别的名字，种子数据却在一个
#: 前端根本不会去查的 scope 里。
DEFAULT_LOCATION_ID = 32000000


def _load(fixtures_dir: Path, name: str) -> dict[str, Any]:
    return json.loads((fixtures_dir / name).read_text(encoding="utf-8"))


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def seed_dev_rankings(
    session: AsyncSession,
    *,
    location_id: int | None = None,
    fixtures_dir: Path | None = None,
) -> dict[str, int]:
    """灌入地区维表与部落榜样本，返回各表写入条数。

    幂等：地区走 upsert，榜单走 ``replace_rankings``（同 scope 先删后插），
    重复跑不会让行数翻倍。
    """
    location_id = location_id if location_id is not None else DEFAULT_LOCATION_ID
    base = fixtures_dir or FIXTURES_DIR

    locations_payload = _load(base, "locations.json")
    location_rows = []
    for item in locations_payload.get("items") or []:
        lid = _int(item.get("id"))
        if lid is None:
            continue
        location_rows.append(
            Location(
                id=lid,
                name=(item.get("name") or "")[:100],
                is_country=bool(item.get("isCountry")),
                country_code=item.get("countryCode"),
            )
        )
    locations_written = await upsert_all(session, Location, location_rows, "id")

    # 两类榜都灌 —— 前端现在只有部落/玩家两个页签，只灌部落会让玩家页空着，
    # 看起来像"玩家榜坏了"。
    clans_written = await replace_rankings(
        session,
        RankingKind.clans,
        location_id,
        None,
        None,
        _load(base, "ranking_clans.json").get("items") or [],
    )
    players_written = await replace_rankings(
        session,
        RankingKind.players,
        location_id,
        None,
        None,
        _load(base, "ranking_players.json").get("items") or [],
    )

    await session.commit()
    return {
        "locations": locations_written,
        "rankings": clans_written + players_written,
        "clans": clans_written,
        "players": players_written,
    }
