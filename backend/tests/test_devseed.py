"""``seed-dev-rankings``：把 app/coc/fixtures 的榜单样本灌进库，供前端联调。

没有真实 Token 时，排行榜接口读的是数据库，不是实时上游——所以需要种子数据。
"""

from sqlalchemy import select

from app.db.models import Ranking
from app.devseed import DEFAULT_LOCATION_ID, seed_dev_rankings


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


async def test_seed_defaults_to_global(session):
    """默认地区是**全服** —— 与采集 job、API 默认值一致。

    不一致的话，夹具模式下会「榜上有数据、但榜单页查不出来」：种子写进一个
    前端根本不会去查的 scope，而页面显示的是另一个地区。
    """
    assert DEFAULT_LOCATION_ID == 32000000

    await seed_dev_rankings(session)
    rows = (await session.execute(select(Ranking))).scalars().all()
    assert rows
    assert all(r.location_id == 32000000 for r in rows)
