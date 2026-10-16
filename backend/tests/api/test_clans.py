"""查询 API：部落与玩家。

覆盖重点是**前端直接依赖的契约**，不是实现细节：

- 统一响应体形状（data + meta，``meta.cache`` 大写）
- 错误码映射（规格 §6.2）
- 分页截断到 50 而非 422（Review Focus 第 4 条）
- STALE 降级（Review Focus 第 3 条）：有缓存时返回 200，无缓存时诚实地 502
- 非法 tag 返回 400 ``INVALID_TAG`` 而非 422

打桩方式：monkeypatch ``app.api.routes.clans.coc`` 上的 endpoint 函数 ——
路由在 import 时绑定了 ``from app.coc import endpoints as coc``，所以
``routes.clans.coc`` 就是路由实际调用的那个对象。
"""

import pytest

from app.api.routes import clans as clans_routes

CLAN_DETAIL = {
    "tag": "#2PP",
    "name": "Reddit Zulu",
    "clanLevel": 18,
    "members": 44,
    "warFrequency": "always",
    "location": {
        "id": 32000001,
        "name": "China",
        "isCountry": True,
        "countryCode": "CN",
    },
    "badgeUrls": {"small": "http://x/s.png"},
    "labels": [{"id": 56000000, "name": "Clan Wars"}],
    "memberList": [
        {
            "tag": "#9QJ8L0",
            "name": "Vasilije",
            "role": "leader",
            "expLevel": 205,
            "trophies": 4902,
            "clanRank": 1,
            "previousClanRank": 1,
            "donations": 2268,
            "donationsReceived": 2182,
            "league": {"id": 29000022, "name": "Legend League"},
        },
        {
            "tag": "#8L9P2R",
            "name": "Covert",
            "role": "coLeader",
            "expLevel": 199,
            "trophies": 4885,
            "builderBaseTrophies": 4712,
            "clanRank": 2,
            "previousClanRank": 2,
            "donations": 210,
            "donationsReceived": 402,
            "league": {"id": 29000021, "name": "Titan League I"},
        },
    ],
}


def _returns(value):
    """造一个返回固定值的 async stub（真实 endpoint 是 async）。"""

    async def stub(*a, **kw):
        return value

    return stub


def _raises(exc):
    """造一个抛指定异常的 async stub。"""

    async def stub(*a, **kw):
        raise exc

    return stub


def _capture(box):
    """造一个记录 kwargs 的 async stub。"""

    async def stub(*a, **kw):
        box.update(kw)
        return {"items": []}

    return stub


@pytest.fixture
def fake_coc(monkeypatch):
    """把某个 coc endpoint 替换成返回固定值或抛指定异常。"""

    def stub(name, result):
        if isinstance(result, Exception):
            monkeypatch.setattr(clans_routes.coc, name, _raises(result))
        else:
            monkeypatch.setattr(clans_routes.coc, name, _returns(result))

    return stub


# --------------------------------------------------------------------------- #
# 部落详情
# --------------------------------------------------------------------------- #


async def test_get_clan_returns_200_with_meta(client, fake_coc):
    fake_coc("get_clan", CLAN_DETAIL)

    resp = await client.get("/api/v1/clans/%232PP")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["tag"] == "#2PP"
    assert body["data"]["name"] == "Reddit Zulu"
    assert body["meta"]["cache"] in {"HIT", "MISS"}
    assert body["meta"]["ttl_seconds"] == 300


async def test_get_clan_lowercase_tag_resolves(client, fake_coc):
    """Review Focus 第 1 条：#2pp 与 #2PP 是同一个部落。"""
    fake_coc("get_clan", CLAN_DETAIL)

    resp = await client.get("/api/v1/clans/2pp")
    assert resp.status_code == 200
    assert resp.json()["data"]["tag"] == "#2PP"


async def test_invalid_tag_returns_400_not_422(client):
    """422 是"参数形状不对"，这里要表达的是"标签不合法"。"""
    resp = await client.get("/api/v1/clans/not-a-tag")
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "INVALID_TAG"
    assert body["error"]["upstream_reason"] is None


async def test_tag_with_only_hash_returns_400(client):
    resp = await client.get("/api/v1/clans/%23")
    assert resp.status_code == 400


async def test_clan_not_found_returns_404(client, fake_coc):
    from app.coc.errors import ClanNotFound

    fake_coc("get_clan", ClanNotFound("部落不存在"))

    resp = await client.get("/api/v1/clans/%23ZZZZ")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CLAN_NOT_FOUND"


def test_player_not_found_code_is_distinct_from_clan():
    from app.api.errors import ERROR_CODE_MAP
    from app.coc.errors import ClanNotFound, PlayerNotFound

    assert ERROR_CODE_MAP[PlayerNotFound] == (404, "PLAYER_NOT_FOUND")
    assert ERROR_CODE_MAP[ClanNotFound] == (404, "CLAN_NOT_FOUND")
    assert ERROR_CODE_MAP[PlayerNotFound] != ERROR_CODE_MAP[ClanNotFound]


# --------------------------------------------------------------------------- #
# STALE 降级（Review Focus 第 3 条）
# --------------------------------------------------------------------------- #


async def test_stale_fallback_returns_200_not_502(client, session, fake_coc):
    """有旧缓存时，官方全线失败也应返回 200 + STALE。"""
    import datetime as dt
    from datetime import UTC

    from app.coc.errors import CocAccessDenied
    from app.coc.mappers import map_clan

    stale = dt.datetime.now(UTC) - dt.timedelta(seconds=600)
    session.add(map_clan(CLAN_DETAIL, now=stale))
    await session.commit()

    fake_coc("get_clan", CocAccessDenied("IP 不在白名单", "accessDenied.invalidIp"))

    resp = await client.get("/api/v1/clans/%232PP")
    assert resp.status_code == 200
    assert resp.json()["meta"]["cache"] == "STALE"


async def test_stale_is_not_used_when_no_prior_data_exists(client, fake_coc):
    """首次部署、库中无任何行时必须诚实地 502，不能伪造成功。"""
    from app.coc.errors import CocAccessDenied

    fake_coc("get_clan", CocAccessDenied("IP 不在白名单", "accessDenied.invalidIp"))

    resp = await client.get("/api/v1/clans/%23FRESH")
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"


async def test_upstream_reason_exposes_access_denied_invalid_ip(client, fake_coc):
    """§7.4 要求 accessDenied.invalidIp 可被单独告警。"""
    from app.coc.errors import CocAccessDenied

    fake_coc("get_clan", CocAccessDenied("denied", "accessDenied.invalidIp"))

    resp = await client.get("/api/v1/clans/%23FRESH")
    assert resp.status_code == 502
    assert resp.json()["error"]["upstream_reason"] == "accessDenied.invalidIp"


# --------------------------------------------------------------------------- #
# 分页（Review Focus 第 4 条）
# --------------------------------------------------------------------------- #


async def test_page_size_above_50_is_capped_not_passed_to_upstream(
    client, monkeypatch
):
    captured = {}
    monkeypatch.setattr(
        clans_routes.coc, "get_clan_members", _capture(captured)
    )

    resp = await client.get("/api/v1/clans/%232PP/members?page_size=500")
    assert resp.status_code == 200
    # 透传给官方会拿到 badRequest（官方只接受 1–50）
    assert captured.get("limit") == 50


async def test_page_size_below_50_passes_through(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        clans_routes.coc, "get_clan_members", _capture(captured)
    )

    resp = await client.get("/api/v1/clans/%232PP/members?page_size=25")
    assert resp.status_code == 200
    assert captured.get("limit") == 25


async def test_clan_members_beyond_first_page_returns_empty_list(client, monkeypatch):
    """越界页返回空列表，不是 404 也不是 500。"""
    monkeypatch.setattr(
        clans_routes.coc,
        "get_clan_members",
        _returns({"items": CLAN_DETAIL["memberList"]}),
    )

    resp = await client.get("/api/v1/clans/%232PP/members?page=999")
    assert resp.status_code == 200
    assert resp.json()["data"] == []


async def test_members_paging_offset_applied(client, monkeypatch):
    """第二页应从 offset 1 开始。"""
    captured = {}
    monkeypatch.setattr(
        clans_routes.coc,
        "get_clan_members",
        _returns({"items": CLAN_DETAIL["memberList"]}),
    )

    resp = await client.get("/api/v1/clans/%232PP/members?page=2&page_size=1")
    assert resp.status_code == 200
    # 库中共 2 名成员，第 2 页（offset=1, limit=1）应剩 1 名
    assert len(resp.json()["data"]) == 1


# --------------------------------------------------------------------------- #
# 搜索
# --------------------------------------------------------------------------- #


async def test_clan_search_passes_query_params(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(clans_routes.coc, "search_clans", _capture(captured))

    resp = await client.get("/api/v1/clans/search?name=Reddit&limit=10")
    assert resp.status_code == 200
    assert captured.get("name") == "Reddit"
    assert captured.get("limit") == 10


async def test_clan_search_empty_name_rejected(client):
    """name 与 locationId 都不给时 400——不能拿空查询打官方。"""
    resp = await client.get("/api/v1/clans/search")
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# 统一响应形状
# --------------------------------------------------------------------------- #


async def test_error_body_shape(client, fake_coc):
    """错误体必须含 code / message / upstream_reason 三个键。"""
    from app.coc.errors import ClanNotFound

    fake_coc("get_clan", ClanNotFound("部落不存在或已失效"))

    resp = await client.get("/api/v1/clans/%23ZZZZ")
    body = resp.json()["error"]
    assert set(body) == {"code", "message", "upstream_reason"}
    assert body["message"] == "部落不存在或已失效"


async def test_meta_shape_on_success(client, fake_coc):
    fake_coc("get_clan", CLAN_DETAIL)
    resp = await client.get("/api/v1/clans/%232PP")
    meta = resp.json()["meta"]
    assert set(meta) == {"cache", "fetched_at", "age_seconds", "ttl_seconds"}
