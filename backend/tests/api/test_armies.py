"""War Report 阵容（配兵）接口。

阵容表是整表替换的：空表意味着"采集还没跑过"，因此必须是 200 + 空列表 +
``meta.cache = "MISS"``，而不是 404 或回源。
"""

import datetime as dt
from datetime import UTC

from app.db.models import WarReportArmy


async def test_armies_ordered_by_position(client, session):
    now = dt.datetime.now(UTC)
    session.add_all([
        WarReportArmy(position=2, name="B", canonical_key="b",
                      army_share_code="s2", army_link="https://b",
                      player_count=1, use_count=2, percentage=20.0,
                      average_stars=2.0, average_destruction=80.0,
                      fetched_at=now),
        WarReportArmy(position=1, name="A", canonical_key="a",
                      army_share_code="s1", army_link="https://a",
                      player_count=2, use_count=3, percentage=30.0,
                      average_stars=3.0, average_destruction=90.0,
                      fetched_at=now),
    ])
    await session.commit()

    resp = await client.get("/api/v1/armies")
    assert resp.status_code == 200
    body = resp.json()
    assert [i["name"] for i in body["data"]["items"]] == ["A", "B"]
    assert body["data"]["items"][0]["armyLink"] == "https://a"
    assert body["meta"]["cache"] == "HIT"


async def test_empty_armies_is_miss(client):
    resp = await client.get("/api/v1/armies")
    assert resp.status_code == 200
    assert resp.json()["data"]["items"] == []
    assert resp.json()["meta"]["cache"] == "MISS"
