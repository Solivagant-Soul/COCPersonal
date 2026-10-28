"""dev 夹具上游：无真实 Token 时用 app/coc/fixtures 应答。

这是**开发期**能力，不是生产路径：只有 ``COC_API_TOKEN`` 为空或占位值时才启用。
夹具响应带 ``_source``/``_todo`` 自报身份，避免被误当真数据。
"""

import httpx

from app.coc.devfixtures import FixtureTransport, is_placeholder_token


def test_placeholder_detection():
    assert is_placeholder_token("")
    assert is_placeholder_token("PLACEHOLDER")
    assert not is_placeholder_token("test-token")


async def test_transport_maps_player_path():
    t = FixtureTransport()
    resp = await t.handle_async_request(
        httpx.Request("GET", "https://x/v1/players/%239QJ8L0")
    )
    assert resp.status_code == 200
    assert resp.json()["tag"].startswith("#")


async def test_transport_unknown_path_is_404_notfound():
    t = FixtureTransport()
    resp = await t.handle_async_request(httpx.Request("GET", "https://x/v1/nope"))
    assert resp.status_code == 404
    assert resp.json()["reason"] == "notFound"


async def test_transport_maps_rankings_path():
    t = FixtureTransport()
    resp = await t.handle_async_request(
        httpx.Request("GET", "https://x/v1/rankings/clans?locationId=32000000")
    )
    assert resp.status_code == 200
    assert isinstance(resp.json()["items"], list)


async def test_transport_maps_player_rankings_path():
    """玩家榜也要有夹具。

    榜单现在只有部落/玩家两类，缺一个就是「无 Token 时玩家页永远空着」，
    而采集 job 每 6 小时都会对着 404 记一次失败。
    """
    t = FixtureTransport()
    resp = await t.handle_async_request(
        httpx.Request(
            "GET", "https://x/v1/locations/32000000/rankings/players?limit=200"
        )
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items
    assert all("tag" in i and "rank" in i for i in items)


async def test_player_rankings_path_is_not_swallowed_by_player_detail_route():
    """``/rankings/players`` 里的 ``/players/`` 不能让它落到玩家详情夹具。

    这是路由顺序的经典坑：玩家详情那条约 ``"/players/" in path``，而
    ``/locations/32000000/rankings/players`` 也含这个子串 —— 判反了就会把
    一整张榜返回成一个玩家的档案。
    """
    t = FixtureTransport()
    resp = await t.handle_async_request(
        httpx.Request("GET", "https://x/v1/locations/32000000/rankings/players")
    )
    body = resp.json()
    assert "items" in body, f"落到了玩家详情夹具：{list(body)[:5]}"
    assert "name" not in body or "items" in body


async def test_transport_maps_clan_and_locations_paths():
    t = FixtureTransport()
    clan = await t.handle_async_request(httpx.Request("GET", "https://x/v1/clans/%232PP"))
    assert clan.status_code == 200
    assert clan.json()["tag"] == "#2PP"

    locs = await t.handle_async_request(httpx.Request("GET", "https://x/v1/locations"))
    assert locs.status_code == 200
    assert isinstance(locs.json()["items"], list)

async def test_transport_maps_player_battlelog_path():
    """``/players/{tag}/battlelog`` 必须落到战报夹具，不能落到玩家详情夹具。

    同样是路由顺序坑：玩家详情那条只判 ``"/players/" in path``，不先判
    ``/battlelog`` 的话，前端拿到的"战报"会是一份玩家档案。
    """
    t = FixtureTransport()
    resp = await t.handle_async_request(
        httpx.Request("GET", "https://x/v1/players/%239QJ8L0/battlelog")
    )
    body = resp.json()
    assert resp.status_code == 200
    assert isinstance(body["items"], list) and body["items"]
    assert "items" in body and "name" not in body
