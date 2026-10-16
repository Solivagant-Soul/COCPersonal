"""CocClient：限流、退避重试、协议校验。

三件事分开测，互不混淆：
1. **协议校验** —— 非 JSON 响应体必须抛 CocProtocolError，而不是把 HTML/纯文本
   当成数据返回（官方偶发返回错误页）。
2. **重试边界** —— 只重试可重试的故障态；业务态与 403 一次都不重试。
3. **退避序列** —— 1s → 2s → 4s，并把 sleep 注入成假函数以免测试真等 7 秒。
"""

from typing import Any

import httpx
import pytest

from app.coc.client import CocClient, STATUS_MAP
from app.coc.errors import (
    CocBusinessError,
    ClanNotFound,
    CocAccessDenied,
    CocProtocolError,
    CocThrottled,
    CocTimeout,
    CocUpstreamError,
    NotInWar,
    PlayerNotFound,
    WarLogPrivate,
)
from app.coc.ratelimit import MemoryRateLimiter


def _recording_handler(calls: list[Any]):
    """把 handler 包成可插入断言的形式，供各用例复用。"""

    def make(handler):
        def wrapped(request):
            calls.append(request)
            return handler(request)

        return wrapped

    return make


def make_client(handler, sleeps: list[float], rate: int = 100) -> CocClient:
    """构造打桩好的 client；sleeps 用于断言退避序列。"""
    client = CocClient(
        "test-token",
        MemoryRateLimiter(rate=rate),
        transport=httpx.MockTransport(handler),
    )

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    client._sleep = fake_sleep  # type: ignore[method-assign]
    return client


# --------------------------------------------------------------------------- #
# 上游地址（R26：走 RoyaleAPI 代理时只换 base_url，路径与鉴权都不变）
# --------------------------------------------------------------------------- #


async def test_client_uses_injected_base_url():
    """`base_url` 必须可注入。

    走 RoyaleAPI 代理时（`https://cocproxy.royaleapi.dev/v1`）只换域名，
    路径与 `Authorization` 头都保持不变 —— 如果把代理域名硬编码进路径拼接，
    或者忘了带上 token，代理会直接 403，且现象与没配白名单一模一样。
    """
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"tag": "#2PP"})

    client = CocClient(
        "test-token",
        MemoryRateLimiter(rate=100),
        base_url="https://cocproxy.royaleapi.dev/v1",
        transport=httpx.MockTransport(handler),
    )
    try:
        await client.get("/clans/%232PP")
    finally:
        await client.aclose()

    assert str(seen[0].url) == "https://cocproxy.royaleapi.dev/v1/clans/%232PP"
    assert seen[0].headers["Authorization"] == "Bearer test-token"


async def test_client_defaults_to_the_official_endpoint():
    """不传 `base_url` 时走官方地址 —— 代理只是可选配置，不是默认依赖。"""
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={})

    client = CocClient(
        "t", MemoryRateLimiter(rate=100), transport=httpx.MockTransport(handler)
    )
    try:
        await client.get("/locations")
    finally:
        await client.aclose()

    assert str(seen[0].url).startswith("https://api.clashofclans.com/v1/")


async def test_settings_fall_back_to_official_when_base_url_blank(monkeypatch):
    """`COC_BASE_URL` 留空 = 走官方。

    .env.example 里它是空值占位；如果不做回退，pydantic 会把空字符串原样
    塞给 httpx，然后每个请求都以 `InvalidURL` 崩掉 —— 而且只在生产配置下炸，
    测试里全用打桩 transport 根本看不出来。
    """
    from app.config import Settings

    monkeypatch.setenv("COC_BASE_URL", "")
    settings = Settings(
        coc_api_token="t",
        database_url="postgresql+asyncpg://x@localhost/x",
        public_base_url="http://localhost",
    )
    assert settings.coc_base_url == "https://api.clashofclans.com/v1"

    # 环境变量也支持直接指向代理
    monkeypatch.setenv("COC_BASE_URL", "https://cocproxy.royaleapi.dev/v1")
    proxied = Settings(
        coc_api_token="t",
        database_url="postgresql+asyncpg://x@localhost/x",
        public_base_url="http://localhost",
    )
    assert proxied.coc_base_url == "https://cocproxy.royaleapi.dev/v1"


async def test_get_returns_parsed_json_and_attaches_token():
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"tag": "#2PP"})

    client = make_client(handler, [])
    try:
        assert await client.get("/clans/%232PP") == {"tag": "#2PP"}
        assert seen[0].headers["authorization"] == "Bearer test-token"
    finally:
        await client.aclose()


async def test_429_triggers_retry_then_succeeds():
    calls: list[httpx.Request] = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, json={"reason": "requestThrottled"})
        return httpx.Response(200, json={"tag": "#2PP"})

    client = make_client(handler, [])
    try:
        assert await client.get("/clans/%232PP") == {"tag": "#2PP"}
        assert len(calls) == 2
    finally:
        await client.aclose()


async def test_403_access_denied_raises_without_retry():
    calls: list[httpx.Request] = []

    def handler(request):
        calls.append(request)
        return httpx.Response(403, json={"reason": "accessDenied.invalidIp"})

    client = make_client(handler, [])
    try:
        with pytest.raises(CocAccessDenied) as exc_info:
            await client.get("/clans/%232PP")
        # 精确 reason 必须带到异常上，否则 §7.4 的 invalidIp 单独告警做不到
        assert exc_info.value.reason == "accessDenied.invalidIp"
        assert len(calls) == 1
    finally:
        await client.aclose()


async def test_404_raises_business_error_without_retry():
    calls: list[httpx.Request] = []

    def handler(request):
        calls.append(request)
        return httpx.Response(404, json={"reason": "notFound"})

    client = make_client(handler, [])
    try:
        with pytest.raises(ClanNotFound):
            await client.get("/clans/%23ZZZZ")
        assert len(calls) == 1
    finally:
        await client.aclose()


async def test_404_not_in_war_maps_to_not_in_war():
    """官方用同一个 404 表达多种业务态，靠 reason 区分。"""

    def handler(request):
        return httpx.Response(404, json={"reason": "notInWar"})

    client = make_client(handler, [])
    try:
        with pytest.raises(NotInWar):
            await client.get("/clans/%232PP/currentwar")
    finally:
        await client.aclose()


async def test_404_private_warlog_maps_to_war_log_private():
    def handler(request):
        return httpx.Response(404, json={"reason": "privateWarLog"})

    client = make_client(handler, [])
    try:
        with pytest.raises(WarLogPrivate):
            await client.get("/clans/%232PP/warlog")
    finally:
        await client.aclose()


async def test_404_unknown_reason_falls_back_to_player_not_found_for_player_path():
    """玩家路径的未知 reason 落 PlayerNotFound，不能被误判成 ClanNotFound。"""

    def handler(request):
        return httpx.Response(404, json={"reason": "someNewReason"})

    client = make_client(handler, [])
    try:
        with pytest.raises(PlayerNotFound):
            await client.get("/players/%239QJ8L0")
    finally:
        await client.aclose()


async def test_exhausted_retries_raises_throttled_with_backoff_sequence():
    calls: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, json={"reason": "requestThrottled"})

    client = make_client(handler, sleeps)
    try:
        with pytest.raises(CocThrottled):
            await client.get("/clans/%232PP")
        assert len(calls) == 4  # 1 + 3 次重试
        assert sleeps == [1.0, 2.0, 4.0]
    finally:
        await client.aclose()


async def test_timeout_is_retried_then_raises_coc_timeout():
    calls: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("timed out")

    client = make_client(handler, sleeps)
    try:
        with pytest.raises(CocTimeout):
            await client.get("/clans/%232PP")
        assert len(calls) == 4
        assert sleeps == [1.0, 2.0, 4.0]
    finally:
        await client.aclose()


async def test_500_maps_to_upstream_error_and_retries():
    calls: list[httpx.Request] = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500, json={})

    client = make_client(handler, [])
    try:
        with pytest.raises(CocUpstreamError):
            await client.get("/clans/%232PP")
        assert len(calls) == 4
    finally:
        await client.aclose()


async def test_non_json_body_raises_protocol_error():
    """200 但 body 是 HTML：绝不能当成功返回。"""

    def handler(request):
        return httpx.Response(200, text="<html>oops</html>", headers={"content-type": "text/html"})

    client = make_client(handler, [])
    try:
        with pytest.raises(CocProtocolError):
            await client.get("/clans/%232PP")
    finally:
        await client.aclose()


async def test_json_missing_reason_field_does_not_crash():
    """响应体没有 reason 字段时不得 KeyError，走默认归位。"""

    def handler(request):
        return httpx.Response(404, json={})

    client = make_client(handler, [])
    try:
        with pytest.raises(ClanNotFound):
            await client.get("/clans/%232PP")
    finally:
        await client.aclose()


async def test_400_bad_request_raises_without_retry():
    """400 是 badRequest，落 CocBusinessError 基类（既非 notFound 也非细分业务态）。"""
    calls: list[httpx.Request] = []

    def handler(request):
        calls.append(request)
        return httpx.Response(400, json={"reason": "badRequest"})

    client = make_client(handler, [])
    try:
        with pytest.raises(CocBusinessError):
            await client.get("/clans/%232PP")
        assert len(calls) == 1
    finally:
        await client.aclose()


async def test_post_sends_json_body_and_returns_parsed():
    seen: dict[str, Any] = {}

    def handler(request):
        seen["body"] = request.content
        return httpx.Response(200, json={"tag": "#9QJ8L0", "status": "ok"})

    client = make_client(handler, [])
    try:
        result = await client.post("/players/%239QJ8L0/verifytoken", {"token": "abc"})
        assert result["status"] == "ok"
        assert b'"token"' in seen["body"] and b'"abc"' in seen["body"]
    finally:
        await client.aclose()


def test_status_map_covers_official_error_codes():
    """漏一个官方状态码 = 漏一类错误的处理，逐项锁住。"""
    for code in (400, 403, 404, 429, 500, 503, 504):
        assert code in STATUS_MAP, f"STATUS_MAP 缺少 {code}"
