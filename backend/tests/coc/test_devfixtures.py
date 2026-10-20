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
        httpx.Request("GET", "https://x/v1/rankings/clans?locationId=32000001")
    )
    assert resp.status_code == 200
    assert isinstance(resp.json()["items"], list)


async def test_transport_maps_clan_and_locations_paths():
    t = FixtureTransport()
    clan = await t.handle_async_request(httpx.Request("GET", "https://x/v1/clans/%232PP"))
    assert clan.status_code == 200
    assert clan.json()["tag"] == "#2PP"

    locs = await t.handle_async_request(httpx.Request("GET", "https://x/v1/locations"))
    assert locs.status_code == 200
    assert isinstance(locs.json()["items"], list)
