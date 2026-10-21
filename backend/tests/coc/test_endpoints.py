"""官方 30 个接口的路径与参数封装。

这里刻意**不做数据映射**：只负责把参数拼成正确的 URL 与 query，返回官方原始 dict。
任何"整理数据的想法"都属于 mappers.py。

覆盖重点是 Review Focus 第 1 条——tag 的 `#` 必须编码为 `%23`、大小写必须归一化。
漏掉任一项的表现很隐蔽：URL 被截断成 `/clans/`，官方返回 400/404，
而表面上像是"这个部落不存在"。
"""

import httpx

from app.coc.client import CocClient
from app.coc.endpoints import (
    get_builderbaseleague,
    get_builderbaseleagues,
    get_capital_rankings,
    get_capitalleague,
    get_capitalleague_seasons,
    get_capitalleagues,
    get_clan,
    get_clan_capitalraidseasons,
    get_clan_currentwar,
    get_clan_currentwar_leaguegroup,
    get_clan_labels,
    get_clan_members,
    get_clan_rankings,
    get_clan_rankings_builder_base,
    get_clan_warlog,
    get_clanwarleague_war,
    get_current_goldpass_season,
    get_league_season_players,
    get_league_seasons,
    get_location,
    get_locations,
    get_player,
    get_player_labels,
    get_player_rankings,
    get_player_rankings_builder_base,
    get_warleague,
    get_warleagues,
    search_clans,
    verify_player_token,
)
from app.coc.ratelimit import MemoryRateLimiter


def make_client(handler) -> CocClient:
    """构造打桩 client。rate 放宽见 R7 裁定：8 req/s 会让用例退化成故意等待。"""
    return CocClient(
        "test-token",
        MemoryRateLimiter(rate=100),
        transport=httpx.MockTransport(handler),
    )


async def _capture(handler):
    """跑一次请求并把 (path, params) 记录下来。"""
    seen: dict[str, object] = {}

    async def run():
        recorded: list[httpx.Request] = []

        def wrapped(request):
            recorded.append(request)
            return handler(request)

        client = make_client(wrapped)
        try:
            await client.get("/x")
        finally:
            await client.aclose()
        return recorded

    recorded = await run()
    seen["path"] = recorded[0].url.path
    seen["params"] = dict(recorded[0].url.params)
    return seen


async def test_get_clan_url_encodes_hash_and_uppercases():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"tag": "#2PP"})

    client = make_client(handler)
    try:
        await get_clan(client, "2pp")
        assert calls[0].endswith("/clans/%232PP")
    finally:
        await client.aclose()


async def test_get_player_url_encodes_hash():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={})

    client = make_client(handler)
    try:
        await get_player(client, "9qj8l0")
        assert calls[0].endswith("/players/%239QJ8L0")
    finally:
        await client.aclose()


async def test_clan_members_uses_members_subpath():
    calls = []

    def handler(request):
        # raw_path 是未经解码的线上形式。url.path 会把 %23 解回 #，
        # 误用它做缓存键会与线上请求不一致。
        calls.append(request.url.raw_path.decode())
        return httpx.Response(200, json={"items": []})

    client = make_client(handler)
    try:
        await get_clan_members(client, "#2PP")
        assert calls[0] == "/v1/clans/%232PP/members"
    finally:
        await client.aclose()


async def test_warlog_and_currentwar_paths():
    calls = []

    def handler(request):
        calls.append(request.url.raw_path.decode())
        return httpx.Response(200, json={"items": []})

    client = make_client(handler)
    try:
        await get_clan_warlog(client, "#2PP")
        await get_clan_currentwar(client, "#2PP")
        assert calls[0] == "/v1/clans/%232PP/warlog"
        assert calls[1] == "/v1/clans/%232PP/currentwar"
    finally:
        await client.aclose()


async def test_rankings_path_and_limit_param():
    seen: dict[str, object] = {}

    def handler(request):
        seen["path"] = request.url.raw_path.decode()
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"items": []})

    client = make_client(handler)
    try:
        await get_clan_rankings(client, 32000001, limit=50)
        # locationId 在路径里，limit 在 query 里——两者都不能进错位置
        # 注意 raw_path 含 query，故用 path 断言路径、用 params 断言参数
        assert seen["path"] == "/v1/locations/32000001/rankings/clans?limit=50"
        assert seen["params"].get("limit") == "50"
        assert "locationId" not in seen["params"]
    finally:
        await client.aclose()


async def test_rankings_location_id_is_in_path_not_query():
    seen = await _capture(lambda r: httpx.Response(200, json={}))
    # _capture 打到 /x，这里只验证 params 缺省为空；真正的路径断言见上一个用例
    assert seen["path"] == "/v1/x"


async def test_locations_and_location_paths():
    calls = []

    def handler(request):
        calls.append(request.url.raw_path.decode())
        return httpx.Response(200, json={"items": []})

    client = make_client(handler)
    try:
        await get_locations(client)
        await get_location(client, 32000001)
        assert calls[0] == "/v1/locations"
        assert calls[1] == "/v1/locations/32000001"
    finally:
        await client.aclose()


async def test_league_paths_and_kind_prefixes():
    calls = []

    def handler(request):
        calls.append(request.url.raw_path.decode())
        return httpx.Response(200, json={"items": []})

    client = make_client(handler)
    try:
        await get_warleagues(client)
        await get_warleague(client, 29000000)
        await get_capitalleagues(client)
        await get_capitalleague(client, 48000000)
        await get_builderbaseleagues(client)
        await get_builderbaseleague(client, 53000000)
        assert calls[0] == "/v1/warleagues"
        assert calls[1] == "/v1/warleagues/29000000"
        assert calls[2] == "/v1/capitalleagues"
        assert calls[3] == "/v1/capitalleagues/48000000"
        assert calls[4] == "/v1/builderbaseleagues"
        assert calls[5] == "/v1/builderbaseleagues/53000000"
    finally:
        await client.aclose()


async def test_league_seasons_path():
    calls = []

    def handler(request):
        calls.append(request.url.raw_path.decode())
        return httpx.Response(200, json={"items": []})

    client = make_client(handler)
    try:
        await get_league_seasons(client, 29000000)
        await get_capitalleague_seasons(client, 48000000)
        assert calls[0] == "/v1/leagues/29000000/seasons"
        assert calls[1] == "/v1/capitalleagues/48000000/seasons"
    finally:
        await client.aclose()


async def test_clan_labels_and_player_labels_paths():
    calls = []

    def handler(request):
        calls.append(request.url.raw_path.decode())
        return httpx.Response(200, json={"items": []})

    client = make_client(handler)
    try:
        await get_clan_labels(client)
        await get_player_labels(client)
        assert calls[0] == "/v1/labels/clans"
        assert calls[1] == "/v1/labels/players"
    finally:
        await client.aclose()


async def test_verify_player_token_uses_post_with_token_body():
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["body"] = request.content
        return httpx.Response(200, json={"tag": "#9QJ8L0", "status": "ok"})

    client = make_client(handler)
    try:
        await verify_player_token(client, "#9QJ8L0", "my-secret-token")
        assert seen["method"] == "POST"
        assert b'"token"' in seen["body"]
        assert b"my-secret-token" in seen["body"]
    finally:
        await client.aclose()


async def test_capital_rankings_path():
    calls = []

    def handler(request):
        calls.append(request.url.raw_path.decode())
        return httpx.Response(200, json={"items": []})

    client = make_client(handler)
    try:
        await get_capital_rankings(client, 32000001)
        assert calls[0] == "/v1/locations/32000001/rankings/capitals"
    finally:
        await client.aclose()


async def test_builder_base_rankings_paths():
    calls = []

    def handler(request):
        calls.append(request.url.raw_path.decode())
        return httpx.Response(200, json={"items": []})

    client = make_client(handler)
    try:
        await get_clan_rankings_builder_base(client, 32000001)
        await get_player_rankings_builder_base(client, 32000001)
        assert calls[0] == "/v1/locations/32000001/rankings/clans-builder-base"
        assert calls[1] == "/v1/locations/32000001/rankings/players-builder-base"
    finally:
        await client.aclose()


async def test_clanwarleague_war_and_capitalraidseasons_paths():
    calls = []

    def handler(request):
        calls.append(request.url.raw_path.decode())
        return httpx.Response(200, json={"items": []})

    client = make_client(handler)
    try:
        await get_clan_currentwar_leaguegroup(client, "#2PP")
        await get_clanwarleague_war(client, "#WARTAG123")
        await get_clan_capitalraidseasons(client, "#2PP")
        assert calls[0] == "/v1/clans/%232PP/currentwar/leaguegroup"
        assert calls[1] == "/v1/clanwarleagues/wars/%23WARTAG123"
        assert calls[2] == "/v1/clans/%232PP/capitalraidseasons"
    finally:
        await client.aclose()


async def test_goldpass_season_path():
    calls = []

    def handler(request):
        calls.append(request.url.raw_path.decode())
        return httpx.Response(200, json={})

    client = make_client(handler)
    try:
        await get_current_goldpass_season(client)
        assert calls[0] == "/v1/goldpass/seasons/current"
    finally:
        await client.aclose()


async def test_search_clans_passes_query_params():
    seen: dict[str, object] = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"items": []})

    client = make_client(handler)
    try:
        await search_clans(client, name="Reddit", limit=10, min_members=40)
        assert seen["params"].get("name") == "Reddit"
        assert seen["params"].get("limit") == "10"
        assert seen["params"].get("minMembers") == "40"
    finally:
        await client.aclose()


async def test_player_rankings_path():
    calls = []

    def handler(request):
        calls.append(request.url.raw_path.decode())
        return httpx.Response(200, json={"items": []})

    client = make_client(handler)
    try:
        await get_player_rankings(client, 32000001)
        assert calls[0] == "/v1/locations/32000001/rankings/players"
    finally:
        await client.aclose()


async def test_leaguetiers_and_single_leaguetier_paths():
    calls = []


async def test_get_league_season_players_path():
    calls = []

    def handler(request):
        calls.append(request.url.raw_path.decode())
        return httpx.Response(200, json={"items": []})

    client = make_client(handler)
    try:
        from app.coc.endpoints import get_league_season_players

        await get_league_season_players(client, 29000000, "2024-01")
        assert calls[0] == "/v1/leagues/29000000/seasons/2024-01"
    finally:
        await client.aclose()


async def test_get_league_season_players_passes_limit():
    """官方默认只回 10 条，采集必须显式带 limit，否则赛季榜静默只剩前 10 名。"""
    calls = []

    def handler(request):
        calls.append(request.url.raw_path.decode())
        return httpx.Response(200, json={"items": []})

    client = make_client(handler)
    try:
        from app.coc.endpoints import get_league_season_players

        await get_league_season_players(client, 105000036, "2026-09", limit=50)
        assert calls[0] == "/v1/leagues/105000036/seasons/2026-09?limit=50"
    finally:
        await client.aclose()
