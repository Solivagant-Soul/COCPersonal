"""战场 API：warlog / currentwar / cwl。

重点是**业务错误绝不降级为 STALE**（Review Focus 第 3 条的负面侧）：

- ``WarLogPrivate`` → 403 ``WARLOG_PRIVATE``，冒泡
- ``NotInWar`` → 404 ``CLAN_NOT_IN_WAR``，冒泡

如果实现把它们降级成 STALE，用户会看到"这个明显没在战的部落有一份当前战数据"，
而且 API 返回 200 —— 排查方向会全错。
"""

import pytest

from app.api.routes import clans as clans_routes
from app.coc.errors import CocUpstreamError, NotInWar, WarLogPrivate

WARLOG_RESPONSE = {
    "clan_tag": "#2PP",
    "items": [
        {
            "end_time": "2026-10-01T08:30:00.000Z",
            "duration": 10800,
            "result": "win",
            "score": 320,
            "opponentScore": 280,
            "opponent": {"tag": "#BBB", "name": "对手"},
            "attacker": {"tag": "#2PP", "name": "Reddit Zulu"},
            "stars": {"attacker": 3, "defender": 1, "difference": 2},
        }
    ],
    "paging": {"cursors": {}},
}

CURRENT_WAR_RESPONSE = {
    "clan_tag": "#2PP",
    "state": "inBattle",
    "war_start_time": "2026-10-01T08:00:00.000Z",
    "war_end_time": "2026-10-02T08:00:00.000Z",
    "war_duration_seconds": 86400,
    "current_score": 120,
    "total_score": 310,
    "attack": {"stars": 18, "clanScore": 120},
    "defense": {"stars": 9, "clanScore": 80},
    "attacker": {"tag": "#2PP", "name": "Reddit Zulu"},
    "defender": {"tag": "#BBB", "name": "对手"},
    "opponent": {"tag": "#BBB", "name": "对手"},
}

CWL_RESPONSE = {
    "clan_tag": "#2PP",
    "current_round": 2,
    "rounds": [
        {"round": 1, "war_tags": ["#W1"]},
        {"round": 2, "war_tags": ["#W2"]},
    ],
}


def _returns(value):
    async def stub(*a, **kw):
        return value

    return stub


def _raises(exc):
    async def stub(*a, **kw):
        raise exc

    return stub


def _capture(box):
    async def stub(*a, **kw):
        box["args"] = a
        box["kwargs"] = kw
        return {}

    return stub


@pytest.fixture
def fake_coc(monkeypatch):
    def stub(name, result):
        if isinstance(result, Exception):
            monkeypatch.setattr(clans_routes.coc, name, _raises(result))
        else:
            monkeypatch.setattr(clans_routes.coc, name, _returns(result))

    return stub


# --------------------------------------------------------------------------- #
# warlog
# --------------------------------------------------------------------------- #


async def test_get_warlog_returns_200(client, fake_coc):
    fake_coc("get_clan_warlog", WARLOG_RESPONSE)

    resp = await client.get("/api/v1/clans/%232PP/warlog")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]["items"]) == 1
    assert body["data"]["items"][0]["result"] == "win"
    assert body["meta"]["ttl_seconds"] == 600


async def test_warlog_private_returns_403(client, fake_coc):
    fake_coc("get_clan_warlog", WarLogPrivate("战报私密"))

    resp = await client.get("/api/v1/clans/%232PP/warlog")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "WARLOG_PRIVATE"


async def test_warlog_private_does_not_degrade_to_stale(client, session, fake_coc):
    """有旧战报 + 战报变私密时，必须冒泡 403 而不是返回旧数据 + 200。

    降级的后果：用户看到的战报是历史数据，而 API 说成功。
    """
    import datetime as dt
    from datetime import UTC

    from app.coc.mappers import map_war_logs
    from app.db.models import Clan

    stale = dt.datetime.now(UTC) - dt.timedelta(seconds=700)
    tag, logs = map_war_logs("#2PP", WARLOG_RESPONSE, now=stale)
    # 战报对 clans 有 FK CASCADE（§5.6），故必须先有父行
    session.add(Clan(tag=tag, name=tag, fetched_at=stale))
    session.add_all(logs)
    await session.commit()

    fake_coc("get_clan_warlog", WarLogPrivate("战报私密"))

    resp = await client.get("/api/v1/clans/%232PP/warlog")
    assert resp.status_code == 403, "业务错误必须冒泡，不得降级为 STALE"
    assert resp.json()["error"]["code"] == "WARLOG_PRIVATE"


async def test_warlog_empty_response_returns_empty_list(client, fake_coc):
    fake_coc("get_clan_warlog", {"items": []})

    resp = await client.get("/api/v1/clans/%232PP/warlog")
    assert resp.status_code == 200
    assert resp.json()["data"]["items"] == []


# --------------------------------------------------------------------------- #
# currentwar
# --------------------------------------------------------------------------- #


async def test_currentwar_returns_200(client, fake_coc):
    fake_coc("get_clan_currentwar", CURRENT_WAR_RESPONSE)

    resp = await client.get("/api/v1/clans/%232PP/currentwar")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["state"] == "inBattle"
    assert body["meta"]["ttl_seconds"] == 120


async def test_currentwar_not_in_war_returns_404_business_code(client, fake_coc):
    fake_coc("get_clan_currentwar", NotInWar("未在战中"))

    resp = await client.get("/api/v1/clans/%232PP/currentwar")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CLAN_NOT_IN_WAR"


async def test_currentwar_not_in_war_does_not_degrade(client, client2=None, **kw):
    """不在战时即便库里有旧的当前战行，也必须冒泡。

    跑两个顺序：先回源成功（落库），再让官方说不在战 —— 若降级，第二次会返回旧行。
    """
    from app.api.routes import clans as routes

    # 第一次：官方有当前战，落库
    async def ok(*a, **kw):
        return CURRENT_WAR_RESPONSE

    original = routes.coc.get_clan_currentwar
    routes.coc.get_clan_currentwar = ok
    try:
        first = await client.get("/api/v1/clans/%232PP/currentwar")
        assert first.status_code == 200

        # 第二次：官方说不在战
        async def not_in_war(*a, **kw):
            raise NotInWar("未在战中")

        routes.coc.get_clan_currentwar = not_in_war
        second = await client.get("/api/v1/clans/%232PP/currentwar")
        assert second.status_code == 404, "不在战必须冒泡 404"
        assert second.json()["error"]["code"] == "CLAN_NOT_IN_WAR"
    finally:
        routes.coc.get_clan_currentwar = original


# --------------------------------------------------------------------------- #
# CWL
# --------------------------------------------------------------------------- #


async def test_cwl_returns_200_with_rounds(client, fake_coc):
    fake_coc("get_clan_currentwar_leaguegroup", CWL_RESPONSE)

    resp = await client.get("/api/v1/clans/%232PP/cwl")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["currentRound"] == 2
    assert len(body["data"]["rounds"]) == 2


async def test_cwl_upstream_failure_is_502(client, fake_coc):
    fake_coc("get_clan_currentwar_leaguegroup", CocUpstreamError("5xx"))

    resp = await client.get("/api/v1/clans/%232PP/cwl")
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"


# --------------------------------------------------------------------------- #
# 占位路由已被替换
# --------------------------------------------------------------------------- #


async def test_warlog_is_no_longer_501(client, fake_coc):
    """Task 9 时的 501 占位必须已被真实实现替换。"""
    fake_coc("get_clan_warlog", WARLOG_RESPONSE)
    resp = await client.get("/api/v1/clans/%232PP/warlog")
    assert resp.status_code != 501


async def test_invalid_tag_on_warlog_returns_400(client):
    resp = await client.get("/api/v1/clans/not-a-tag/warlog")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_TAG"