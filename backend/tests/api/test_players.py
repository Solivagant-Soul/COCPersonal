"""查询 API：玩家侧。

补充部落侧未覆盖的部分：玩家 404 的独立错误码、verifytoken 的 POST 契约、
以及玩家档案的 STALE 降级。

打桩目标：``app.api.routes.players.coc`` —— 玩家路由自己持有的 endpoint 引用。
"""

import pytest

from app.api.routes import players as players_routes

PLAYER_PROFILE = {
    "tag": "#9QJ8L0",
    "name": "Vasilije",
    "townHallLevel": 16,
    "expLevel": 205,
    "trophies": 4902,
    "clan": {"tag": "#2PP", "name": "Reddit Zulu", "clanLevel": 18},
    "role": "leader",
    "league": {"id": 29000022, "name": "Legend League"},
}


def _returns(value):
    async def stub(*a, **kw):
        return value

    return stub


def _raises(exc):
    async def stub(*a, **kw):
        raise exc

    return stub


@pytest.fixture
def fake_coc(monkeypatch):
    def stub(name, result):
        if isinstance(result, Exception):
            monkeypatch.setattr(players_routes.coc, name, _raises(result))
        else:
            monkeypatch.setattr(players_routes.coc, name, _returns(result))

    return stub


async def test_get_player_returns_200(client, fake_coc):
    fake_coc("get_player", PLAYER_PROFILE)

    resp = await client.get("/api/v1/players/%239QJ8L0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["tag"] == "#9QJ8L0"
    assert body["data"]["townHallLevel"] == 16
    assert body["meta"]["cache"] in {"HIT", "MISS"}


async def test_get_player_lowercase_tag(client, fake_coc):
    fake_coc("get_player", PLAYER_PROFILE)

    resp = await client.get("/api/v1/players/9qj8l0")
    assert resp.status_code == 200
    assert resp.json()["data"]["tag"] == "#9QJ8L0"


async def test_player_not_found_returns_404_with_player_code(client, fake_coc):
    from app.coc.errors import PlayerNotFound

    fake_coc("get_player", PlayerNotFound("玩家不存在"))

    resp = await client.get("/api/v1/players/%23ZZZZ")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PLAYER_NOT_FOUND"


async def test_second_player_request_hits_cache_and_skips_upstream(client, monkeypatch):
    """玩家详情同部落详情：TTL 内第二次请求必须 HIT 且不回源。

    玩家路由的 loader 同样返回 dict（``{"_row": ..., "fetched_at": ...}``），
    所以也踩过「属性 vs 映射」这个坑。
    """
    calls = []

    async def counting_stub(*a, **kw):
        calls.append(1)
        return PLAYER_PROFILE

    monkeypatch.setattr(players_routes.coc, "get_player", counting_stub)

    first = await client.get("/api/v1/players/%239QJ8L0")
    second = await client.get("/api/v1/players/%239QJ8L0")

    assert first.json()["meta"]["cache"] == "MISS"
    assert second.json()["meta"]["cache"] == "HIT"
    assert len(calls) == 1, "TTL 内的第二次请求不该回源"
    assert second.json()["meta"]["age_seconds"] is not None
    assert second.json()["data"]["name"] == "Vasilije"
    assert second.json()["data"]["expLevel"] == 205


async def test_invalid_player_tag_returns_400(client):
    resp = await client.get("/api/v1/players/not-a-tag")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_TAG"


async def test_player_stale_fallback(client, session, fake_coc):
    """玩家侧同样要降级：官方挂了但库里有旧档案时返回 200。"""
    import datetime as dt
    from datetime import UTC

    from app.coc.errors import CocAccessDenied
    from app.coc.mappers import map_player

    stale = dt.datetime.now(UTC) - dt.timedelta(seconds=600)
    session.add(map_player(PLAYER_PROFILE, now=stale))
    await session.commit()

    fake_coc("get_player", CocAccessDenied("IP 不在白名单", "accessDenied.invalidIp"))

    resp = await client.get("/api/v1/players/%239QJ8L0")
    assert resp.status_code == 200
    assert resp.json()["meta"]["cache"] == "STALE"


async def test_verify_player_token_returns_200_with_status(client, monkeypatch):
    monkeypatch.setattr(
        players_routes.coc,
        "verify_player_token",
        _returns({"tag": "#9QJ8L0", "token": "t", "status": "ok"}),
    )

    resp = await client.post(
        "/api/v1/players/%239QJ8L0/verifytoken", json={"token": "t"}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ok"
    assert resp.json()["data"]["tag"] == "#9QJ8L0"


async def test_verify_player_token_requires_token_field(client):
    """缺 token 字段必须 400，不能透一个空 token 给官方。"""
    resp = await client.post("/api/v1/players/%239QJ8L0/verifytoken", json={})
    assert resp.status_code in (400, 422)
    assert "error" in resp.json()


async def test_verify_token_calls_official_with_token(client, monkeypatch):
    captured = {}

    async def capture(*args, **kw):
        # 路由用位置参数调 endpoint（client, tag, token），故 args 也要记
        captured["args"] = args
        captured["kwargs"] = kw
        return {"tag": "#9QJ8L0", "status": "ok"}

    monkeypatch.setattr(players_routes.coc, "verify_player_token", capture)

    await client.post(
        "/api/v1/players/%239QJ8L0/verifytoken", json={"token": "my-token"}
    )
    assert "my-token" in captured["args"], "token 必须透传给官方"


def test_player_not_found_and_clan_not_found_have_distinct_codes():
    from app.api.errors import ERROR_CODE_MAP
    from app.coc.errors import ClanNotFound, PlayerNotFound

    assert ERROR_CODE_MAP[PlayerNotFound][1] == "PLAYER_NOT_FOUND"
    assert ERROR_CODE_MAP[ClanNotFound][1] == "CLAN_NOT_FOUND"
