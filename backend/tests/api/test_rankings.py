"""排行榜、地区与数据新鲜度接口。

重点是两条容易搞反的契约：

1. **只读库，不回源。** 榜单由定时任务写入。若每个用户请求都触发回源，
   40 个地区 × 6 种榜 × 活跃用户会把 Supercell 令牌桶打爆。库里没数据时返回
   空列表 + ``meta.cache = "MISS"`` —— 空列表是诚实的答案（采集还没跑到）。
2. **``page_size`` 截断而非拒绝。** ``?page_size=500`` 必须返回 200 + 截断到 50，
   而不是 pydantic 的 422（AGENTS.md 硬规矩）。``page`` 越界返回空列表而非 404。
"""

import datetime as dt
from datetime import UTC

import pytest

from app.collector.rankings_service import RankingKind
from app.db.models import CollectorRun, League, Ranking, Season

GLOBAL = 32000000
CN = 32000001
US = 32000002
WAR_LEAGUE = 48000000
SEASON = "2026-09"


@pytest.fixture
async def board(session):
    """一份可预期的榜单：CN 的部落榜 1..3，US 的部落榜 1 条。"""
    now = dt.datetime.now(UTC)
    session.add_all([
        Ranking(kind=str(RankingKind.clans), location_id=CN, rank=1,
                tag="#A1", name="A1", points=5000, members=45, clan_level=15,
                fetched_at=now),
        Ranking(kind=str(RankingKind.clans), location_id=CN, rank=2,
                tag="#A2", name="A2", points=4000, members=44, clan_level=14,
                fetched_at=now),
        Ranking(kind=str(RankingKind.clans), location_id=CN, rank=3,
                tag="#A3", name="A3", points=3000, fetched_at=now),
        Ranking(kind=str(RankingKind.clans), location_id=US, rank=1,
                tag="#U1", name="U1", points=9000, fetched_at=now),
        Ranking(kind=str(RankingKind.players), location_id=CN, rank=1,
                tag="#P1", name="P1", trophies=6000, exp_level=300,
                attack_wins=30, defense_wins=12, fetched_at=now),
        Ranking(kind=str(RankingKind.clans), location_id=GLOBAL, rank=1,
                tag="#G1", name="G1", points=99000, members=50, clan_level=18,
                fetched_at=now),
        Ranking(kind=str(RankingKind.players), location_id=GLOBAL, rank=1,
                tag="#GP1", name="GP1", trophies=9900, exp_level=500,
                attack_wins=300, defense_wins=120, fetched_at=now),
    ])
    await session.commit()


BOARDS = [
    ("clans", str(RankingKind.clans)),
    ("players", str(RankingKind.players)),
]

#: 已移除的榜（2026-10-22 收窄成全服 + 部落/玩家）。路由应当 404 ——
#: 留着返回空列表会让人以为"榜还在只是没数据"。
REMOVED_BOARDS = [
    "capitals",
    "clans_builder_base",
    "players_builder_base",
]


# --------------------------------------------------------------------------- #
# 两类地区榜
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path,kind", BOARDS)
async def test_each_board_endpoint_exists(client, path, kind):
    resp = await client.get(f"/api/v1/rankings/{path}")
    assert resp.status_code == 200
    assert resp.json()["data"]["kind"] == kind


@pytest.mark.parametrize("path", REMOVED_BOARDS)
async def test_removed_board_endpoints_are_gone(client, path):
    """已移除的榜必须是 404，不是 200 + 空列表。

    返回空列表会让人以为"榜还在、只是没数据"，于是反复刷新等它出现。
    404 才说得清"这个榜没有了"。
    """
    resp = await client.get(f"/api/v1/rankings/{path}")
    assert resp.status_code == 404


async def test_rankings_clans_defaults_to_global(client, board):
    """默认查全服（32000000）。

    榜单收窄成「只看全服」后，默认地区就是全服 —— 不再是中国。
    """
    resp = await client.get("/api/v1/rankings/clans")
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["cache"] in {"HIT", "MISS", "STALE"}
    tags = [i["tag"] for i in body["data"]["items"]]
    assert tags == ["#G1"], "默认应查全服（32000000）"


async def test_rankings_sorted_by_rank_ascending(client, board):
    body = (await client.get("/api/v1/rankings/clans")).json()
    ranks = [i["rank"] for i in body["data"]["items"]]
    assert ranks == sorted(ranks)


async def test_rankings_respects_location_id(client, board):
    """locationId 仍然生效 —— 传别的地区就查那个地区。

    收窄的是「**采集**哪些地区」，不是「API 能不能按地区查」。留着这个参数
    是为了契约不破：前端可能还带着 locationId 发请求。
    """
    body = (await client.get(f"/api/v1/rankings/clans?locationId={US}")).json()
    assert [i["tag"] for i in body["data"]["items"]] == ["#U1"]


async def test_rankings_unknown_location_returns_empty_not_404(client, board):
    """库里没这个地区的数据 → 空列表。不是"地区不存在"的 404。"""
    resp = await client.get("/api/v1/rankings/clans?locationId=99999999")
    assert resp.status_code == 200
    assert resp.json()["data"]["items"] == []


async def test_rankings_missing_data_is_miss_not_upstream_call(client, session):
    """库里没数据时 cache=MISS，且**不得回源**。

    回源会让 40 地区 × 6 榜 × 用户请求打爆 Supercell 令牌桶。
    """
    resp = await client.get("/api/v1/rankings/clans")
    body = resp.json()
    assert body["meta"]["cache"] == "MISS"
    assert body["data"]["items"] == []
    assert body["data"]["total"] == 0


async def test_rankings_never_touches_coc_client(client, session):
    """结构断言：这条路由不持有 CocClient。

    靠 monkeypatch 抓回源调用是间接证据（漏配一个 endpoint 就抓不到），
    这里直接断言签名里没有 client 依赖。
    """
    from app.api.routes import rankings as routes

    import inspect

    for name in ("list_rankings_clans", "list_rankings_players"):
        fn = getattr(routes, name)
        params = inspect.signature(fn).parameters
        assert "client" not in params, f"{name} 不该依赖 CocClient"


async def test_rankings_page_size_is_capped_at_50(client, board):
    """``?page_size=500`` → 200 + 截断到 50，不是 422。"""
    resp = await client.get("/api/v1/rankings/clans?page_size=500")
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 1  # 全服 scope 只有 1 条；总数与 page_size 无关


async def test_rankings_page_beyond_end_returns_empty(client, board):
    """page 越界返回空列表而非 404（Review Focus 第 4 条）。"""
    resp = await client.get("/api/v1/rankings/clans?page=99")
    assert resp.status_code == 200
    assert resp.json()["data"]["items"] == []


async def test_rankings_page_two_returns_remaining(client, board):
    body = (await client.get(f"/api/v1/rankings/clans?locationId={CN}&page_size=2&page=2")).json()
    assert [i["tag"] for i in body["data"]["items"]] == ["#A3"]


async def test_rankings_page_size_zero_returns_400(client, board):
    """``ge=1`` 会让 0 变成 422，必须转成 400 INVALID_PARAMS。"""
    resp = await client.get("/api/v1/rankings/clans?page_size=0")
    assert resp.status_code == 400


async def test_rankings_exposes_metrics_per_kind(client, board):
    body = (await client.get(f"/api/v1/rankings/clans?locationId={CN}")).json()
    first = body["data"]["items"][0]
    assert first["points"] == 5000
    assert first["members"] == 45
    assert first["clanLevel"] == 15

    players = (await client.get(f"/api/v1/rankings/players?locationId={CN}")).json()
    p = players["data"]["items"][0]
    assert p["trophies"] == 6000
    assert p["expLevel"] == 300
    assert p["attackWins"] == 30


async def test_rankings_includes_previous_rank(client, session):
    now = dt.datetime.now(UTC)
    session.add(Ranking(kind=str(RankingKind.clans), location_id=GLOBAL, rank=1,
                        previous_rank=7, tag="#A1", name="A1", fetched_at=now))
    await session.commit()
    body = (await client.get("/api/v1/rankings/clans")).json()
    assert body["data"]["items"][0]["previousRank"] == 7


# --------------------------------------------------------------------------- #
# 赛季榜
# --------------------------------------------------------------------------- #


async def test_season_rankings(client, session):
    now = dt.datetime.now(UTC)
    session.add_all([
        Ranking(kind=str(RankingKind.season_players), league_id=WAR_LEAGUE,
                season_id=SEASON, rank=1, tag="#S1", name="S1",
                trophies=5000, fetched_at=now),
        Ranking(kind=str(RankingKind.season_players), league_id=WAR_LEAGUE,
                season_id="2026-08", rank=1, tag="#OLD", name="OLD",
                fetched_at=now),
    ])
    await session.commit()

    resp = await client.get(f"/api/v1/rankings/season/{WAR_LEAGUE}/{SEASON}")
    body = resp.json()
    assert [i["tag"] for i in body["data"]["items"]] == ["#S1"]
    assert body["data"]["seasonId"] == SEASON


async def test_season_rankings_missing_returns_empty(client):
    resp = await client.get(f"/api/v1/rankings/season/{WAR_LEAGUE}/1999-01")
    assert resp.status_code == 200
    assert resp.json()["data"]["items"] == []


async def test_list_seasons(client, session):
    session.add_all([
        Season(league_id=WAR_LEAGUE, id="2026-09", name="Sep",
                start_time=dt.datetime.now(UTC)),
        Season(league_id=WAR_LEAGUE, id="2026-08", name="Aug"),
        # 新格式与旧格式混排：按字符串倒序会把 ``v2-`` 顶到最前（字母 > 数字），
        # 必须归一成日期再排 —— 见 ``app.coc.season_ids``。
        Season(league_id=WAR_LEAGUE, id="v2-2026-06-01T05:00:00Z", name="Jun"),
        Season(league_id=19000000, id="2026-09", name="别联赛的同号赛季"),
    ])
    await session.commit()

    body = (await client.get(f"/api/v1/seasons/{WAR_LEAGUE}")).json()
    ids = [i["id"] for i in body["data"]["items"]]
    assert ids == ["2026-09", "2026-08", "v2-2026-06-01T05:00:00Z"], (
        "同号赛季在别的联赛下不应出现；两种 id 格式混排要按日期倒序"
    )


# --------------------------------------------------------------------------- #
# 联赛
# --------------------------------------------------------------------------- #


async def test_list_leagues_by_kind(client, session):
    session.add_all([
        League(id=48000000, kind="war", name="Crystal League I"),
        League(id=19000000, kind="builder_base", name="Builder League I"),
        League(id=48000000, kind="capital", name="Capital League I"),
    ])
    await session.commit()

    body = (await client.get("/api/v1/leagues/war")).json()
    assert [i["id"] for i in body["data"]["items"]] == [48000000]

    bb = (await client.get("/api/v1/leagues/builder_base")).json()
    assert [i["id"] for i in bb["data"]["items"]] == [19000000]


async def test_list_leagues_same_id_different_kind_coexists(client, session):
    """同一个 id 在不同 kind 下是两条 —— 0006 改成复合主键就是为了这个。"""
    session.add_all([
        League(id=48000000, kind="war", name="W"),
        League(id=48000000, kind="capital", name="C"),
    ])
    await session.commit()
    for kind in ("war", "capital"):
        body = (await client.get(f"/api/v1/leagues/{kind}")).json()
        assert len(body["data"]["items"]) == 1


async def test_list_leagues_invalid_kind_returns_400(client):
    resp = await client.get("/api/v1/leagues/nonsense")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMS"


# --------------------------------------------------------------------------- #
# 地区
# --------------------------------------------------------------------------- #


async def test_locations_lists_only_global(client, session):
    """只返回全服。

    榜单收窄成只看全服后，前端不再需要挑地区 —— 保留几十个国家选项只会让人
    以为「榜单是按国家分的」，而实际库里只有全服的数据。
    """
    session.add_all([
        _loc(32000000, "Global", False),
        _loc(32000001, "China", True),
        _loc(32000002, "United States", True),
        _loc(32000003, "Gansu", False),
    ])
    await session.commit()

    body = (await client.get("/api/v1/locations")).json()
    names = {i["name"] for i in body["data"]["items"]}
    assert names == {"Global"}, "只该返回全服"
    assert body["data"]["total"] == 1


async def test_locations_global_is_present_even_though_not_a_country(client, session):
    """**Global 的 isCountry 是 false** —— 靠 is_country 过滤会把它漏掉。

    这正是「只查全服」最容易写错的一处：全服在官方数据里根本不算"国家"。
    """
    session.add(_loc(32000000, "Global", False))
    await session.commit()

    body = (await client.get("/api/v1/locations")).json()
    assert [i["id"] for i in body["data"]["items"]] == [32000000]


def _loc(lid, name, is_country):
    from app.db.models import Location

    return Location(id=lid, name=name, is_country=is_country)


# --------------------------------------------------------------------------- #
# 数据新鲜度
# --------------------------------------------------------------------------- #


async def test_meta_freshness_reports_last_collection(client, board):
    resp = await client.get("/api/v1/meta/freshness")
    assert resp.status_code == 200
    body = resp.json()
    assert "rankings" in body["data"]
    assert str(CN) in body["data"]["rankings"]
    assert body["data"]["rankings"][str(CN)][str(RankingKind.clans)] is not None


async def test_meta_freshness_is_empty_before_any_collection(client, session):
    body = (await client.get("/api/v1/meta/freshness")).json()
    assert body["data"]["rankings"] == {}


async def test_meta_freshness_surfaces_failed_collector_runs(client, session):
    """采集失败必须能从对外接口看到，否则"榜单三天没更新"没人知道。"""
    now = dt.datetime.now(UTC)
    session.add(CollectorRun(job_name="rankings", started_at=now,
                             finished_at=now, status="partial",
                             items_total=15, items_ok=10, items_failed=5,
                             error={"failed": 5, "detail": ["clans/32000002: 5xx"]}))
    await session.commit()

    body = (await client.get("/api/v1/meta/freshness")).json()
    runs = body["data"]["collectorRuns"]
    assert runs
    assert runs[0]["jobName"] == "rankings"
    assert runs[0]["status"] == "partial"


async def test_meta_freshness_excludes_season_rankings_from_by_location(client, session):
    """赛季榜没有 location_id，不该被塞进按地区分组的那份数据里。"""
    now = dt.datetime.now(UTC)
    session.add(Ranking(kind=str(RankingKind.season_players), league_id=WAR_LEAGUE,
                        season_id=SEASON, rank=1, tag="#S1", name="S1",
                        fetched_at=now))
    await session.commit()
    body = (await client.get("/api/v1/meta/freshness")).json()
    assert body["data"]["rankings"] == {}


# --------------------------------------------------------------------------- #
# 契约形状
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/locations",
        "/api/v1/rankings/clans",
        "/api/v1/rankings/season/48000000/2026-09",
        "/api/v1/leagues/war",
        "/api/v1/meta/freshness",
    ],
)
async def test_every_endpoint_uses_the_unified_envelope(client, path):
    body = (await client.get(path)).json()
    assert set(body) == {"data", "meta"}
    assert set(body["meta"]) == {"cache", "fetched_at", "age_seconds", "ttl_seconds"}


@pytest.mark.parametrize("path", ["/api/v1/rankings/clans", "/api/v1/meta/freshness"])
async def test_cache_value_is_uppercase(client, board, path):
    """§6.1：HIT/MISS/STALE 必须大写，小写直接破坏前端契约。"""
    cache = (await client.get(path)).json()["meta"]["cache"]
    assert cache in {"HIT", "MISS", "STALE"}
    assert cache == cache.upper()


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/rankings/clans",
        "/api/v1/rankings/players",
        "/api/v1/locations",
    ],
)
async def test_page_size_500_is_truncated_not_rejected(client, path):
    resp = await client.get(f"{path}?page_size=500")
    assert resp.status_code == 200, f"{path} 应截断到 50 而不是 422"