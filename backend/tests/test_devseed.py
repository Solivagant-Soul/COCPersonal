"""``seed-dev-rankings``：把 tests/fixtures 的榜单样本灌进库，供前端联调。

没有真实 Token 时，排行榜接口读的是数据库，不是实时上游——所以需要种子数据。
"""

from sqlalchemy import select

from app.db.models import Ranking
from app.devseed import seed_dev_rankings


async def test_seed_writes_rankings(session):
    counts = await seed_dev_rankings(session, location_id=32000001)
    assert counts["rankings"] > 0

    rows = (
        await session.execute(select(Ranking).where(Ranking.kind == "clans"))
    ).scalars().all()
    assert rows and rows[0].location_id == 32000001


async def test_seed_writes_locations_for_frontend(session):
    counts = await seed_dev_rankings(session, location_id=32000001)
    assert counts["locations"] > 0


async def test_seed_then_api_returns_items(client, session):
    await seed_dev_rankings(session, location_id=32000001)

    resp = await client.get("/api/v1/rankings/clans?locationId=32000001")
    assert resp.status_code == 200
    assert resp.json()["data"]["items"]
