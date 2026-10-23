"""War Report 赛季榜接口。

三条容易搞反的契约：

1. **赛季列表最多 3 个**，且每个赛季的 ``players`` / ``clans`` 是各自的条数。
2. **未知快照返回 200 + 空列表**，不是 404 —— 快照每天都可能新增，用户手里的
   旧链接不该变成错误。
3. **快照校验是两步**：正则只拦形状（``2026-13-99`` 完全符合
   ``^\\d{4}-\\d{2}-\\d{2}$``），日历合法性要再走一次 ``date.fromisoformat``。
"""

import datetime as dt
from datetime import UTC

import pytest

from app.collector.rankings_service import RankingKind
from app.db.models import Ranking

GLOBAL = 32000000
S1, S2 = "2026-10-05", "2026-09-07"


@pytest.fixture
async def boards(session):
    now = dt.datetime.now(UTC)
    rows = []
    for season in (S1, S2):
        for rank in range(1, 61):
            rows.append(Ranking(
                kind=str(RankingKind.wr_season_players), location_id=GLOBAL,
                season_id=season, rank=rank, tag=f"#P{rank}", name=f"P{rank}",
                trophies=6000 - rank, exp_level=300, fetched_at=now,
            ))
        rows.append(Ranking(
            kind=str(RankingKind.wr_season_clans), location_id=GLOBAL,
            season_id=season, rank=1, tag="#C1", name="C1",
            points=5000, members=45, clan_level=18, fetched_at=now,
        ))
    session.add_all(rows)
    await session.commit()


async def test_seasons_listed_newest_first_with_counts(client, boards):
    resp = await client.get("/api/v1/rankings/warreport/seasons")
    assert resp.status_code == 200
    body = resp.json()
    items = body["data"]["items"]
    assert [i["seasonId"] for i in items] == [S1, S2]
    assert items[0]["players"] == 60
    assert items[0]["clans"] == 1
    # fetchedAt 是 ISO 串（来自 max(fetched_at)），只断言存在且非空
    assert items[0]["fetchedAt"]
    assert body["meta"]["cache"] == "HIT"
    assert body["meta"]["ttl_seconds"] == 86400


async def test_seasons_capped_at_three(client, boards, session):
    """最多给 3 季 —— 多出来的旧快照不返回（采集侧也只保留最近 3 个）。"""
    now = dt.datetime.now(UTC)
    session.add_all([
        Ranking(kind=str(RankingKind.wr_season_clans), location_id=GLOBAL,
                season_id=season, rank=1, tag="#C1", name="C1",
                points=1, members=1, clan_level=1, fetched_at=now)
        for season in ("2026-08-01", "2026-07-01")
    ])
    await session.commit()

    resp = await client.get("/api/v1/rankings/warreport/seasons")
    seasons = [i["seasonId"] for i in resp.json()["data"]["items"]]
    assert seasons == [S1, S2, "2026-08-01"]


async def test_season_board_paginates_and_clamps(client, boards):
    resp = await client.get(
        f"/api/v1/rankings/warreport/seasons/{S1}/players?page_size=100"
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["items"]) == 50
    assert data["total"] == 60
    assert data["kind"] == "players"


async def test_missing_snapshot_returns_empty_200(client, boards):
    resp = await client.get(
        "/api/v1/rankings/warreport/seasons/2026-01-01/players"
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["items"] == []


@pytest.mark.parametrize(
    "path",
    [
        # 月份 13 / 日期 99 合法形状但非法值
        "/api/v1/rankings/warreport/seasons/2026-13-99/players",
        # 少一位补零 —— 正则要求严格 \d{4}-\d{2}-\d{2}
        "/api/v1/rankings/warreport/seasons/2026-10-5/players",
        "/api/v1/rankings/warreport/seasons/not-a-date/players",
        f"/api/v1/rankings/warreport/seasons/{S1}/foo",
    ],
)
async def test_invalid_snapshot_or_kind_is_400(client, path):
    resp = await client.get(path)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMS"


async def test_page_beyond_last_is_empty_200(client, boards):
    resp = await client.get(
        f"/api/v1/rankings/warreport/seasons/{S1}/players?page=999"
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["items"] == []
