"""Supercell 官方 API 的 HTTP 客户端。

职责边界：只管 HTTP 层的三件事 —— 限速、退避重试、把响应翻译成
`app.coc.errors` 的异常。**不**做任何数据映射（那是 `mappers.py` 的事），
也**不**缓存（那是 `cache/` 的事）。

可重试与不可重试的分界是本模块的核心契约：

- 429 / 500 / 503 / 504 / 超时 → 可重试，最多 3 次，退避 1s → 2s → 4s
- 业务态 400 / 404 → 一次都不重试，立即抛对应异常
- 403 → 一次都不重试（IP 白名单不匹配时重试只会白烧令牌桶额度）
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.coc.errors import (
    ClanNotFound,
    CocAccessDenied,
    CocBusinessError,
    CocError,
    CocFaultError,
    CocProtocolError,
    CocThrottled,
    CocTimeout,
    CocUpstreamError,
    NotInWar,
    PlayerNotFound,
    WarLogPrivate,
)
from app.coc.ratelimit import RateLimiter

#: 官方地址（默认）。**走 RoyaleAPI 代理时在配置里覆盖它**（``COC_BASE_URL``），
#: 路径与鉴权方式都不变 —— 代理只是换域名转发，
#: 所以错误码、reason 与响应形状与本文件的全部假设一致。
BASE_URL = "https://api.clashofclans.com/v1"
MAX_RETRIES = 3

# 状态码 → 异常类型。404 需再按 reason 细分，见 _error_from_response。
STATUS_MAP: dict[int, type[CocError]] = {
    400: CocBusinessError,
    403: CocAccessDenied,
    404: ClanNotFound,
    429: CocThrottled,
    500: CocUpstreamError,
    503: CocUpstreamError,
    504: CocUpstreamError,
}

# 404 下的业务态细分。官方端口同一个 404 表达多种含义。
_NOT_FOUND_REASONS = {
    "notFound": None,  # 按路径落 ClanNotFound / PlayerNotFound
    "notInWar": NotInWar,
    "privateWarLog": WarLogPrivate,
}


class CocClient:
    """Supercell API 客户端。

    ``transport`` 是测试注入点：测试用 ``httpx.MockTransport``，
    生产用默认的异步传输。
    """

    def __init__(
        self,
        token: str,
        rate_limiter: RateLimiter,
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        self._token = token
        self._limiter = rate_limiter
        self._timeout = timeout
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={"Authorization": f"Bearer {token}"},
        )
        # 注入点：测试替换为记录调用的假函数，断言退避序列而不真等
        self._sleep: Callable[[float], Awaitable[None]] = asyncio.sleep

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ #
    # 公开接口
    # ------------------------------------------------------------------ #

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", path, json_body=json_body)

    # ------------------------------------------------------------------ #
    # 内部实现
    # ------------------------------------------------------------------ #

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        last_error: CocError | None = None

        for attempt in range(MAX_RETRIES + 1):
            await self._limiter.acquire()
            try:
                response = await self._client.request(
                    method, path, params=params, json=json_body
                )
            except httpx.TimeoutException as exc:
                last_error = CocTimeout(f"{method} {path} 超时: {exc}")
            else:
                status = response.status_code
                if status < 400:
                    return _parse_json(response, path)

                error = _error_from_response(method, path, status, response)
                # 业务态与 403 绝不在重试范围内，直接让调用方看到真实原因
                if not isinstance(error, (CocFaultError,)):
                    raise error
                last_error = error

            # 只对故障态退避；最后一次失败也不再睡，直接抛出
            if attempt < MAX_RETRIES:
                await self._sleep(2**attempt)

        assert last_error is not None
        raise last_error


def _parse_json(response: httpx.Response, path: str) -> dict[str, Any]:
    """把响应体解析成 dict。

    非 JSON 或顶层不是对象都算协议错误 —— 官方偶发会返回 HTML 错误页，
    若放过去，调用方会拿到一个长得像数据的字符串。
    """
    try:
        data = response.json()
    except ValueError as exc:
        raise CocProtocolError(f"{path} 返回了非 JSON 响应体: {exc}") from exc
    if not isinstance(data, dict):
        raise CocProtocolError(
            f"{path} 的 JSON 顶层不是对象: {type(data).__name__}"
        )
    return data


def _error_from_response(
    method: str, path: str, status: int, response: httpx.Response
) -> CocError:
    """按状态码与 reason 翻译异常。

    reason 缺失或解析失败都不抛新异常，按状态码的默认归位处理 ——
    宁可给一个粗糙但确定的错误，也不要因为读响应体而再炸一次。
    """
    try:
        payload = response.json()
        reason = payload.get("reason") if isinstance(payload, dict) else None
        message = payload.get("message") if isinstance(payload, dict) else None
    except ValueError:
        payload, reason, message = {}, None, None

    if status == 404:
        mapped = _NOT_FOUND_REASONS.get(reason, None)
        if mapped is not None:
            return mapped(message or f"{path} 不存在")
        # notFound 或未知 reason：按路径落 ClanNotFound / PlayerNotFound
        if path.startswith("/players"):
            return PlayerNotFound(message or f"玩家不存在: {path}")
        return ClanNotFound(message or f"部落不存在: {path}")

    error_class = STATUS_MAP.get(status)
    if error_class is None:
        # 未收录的状态码按上游异常处理，绝不静默当成功
        return CocUpstreamError(f"未预期的状态码 {status}: {path}")
    if error_class is CocAccessDenied:
        # 把精确 reason 带上去，供 §7.4 的 invalidIp 单独告警使用
        return CocAccessDenied(message or f"访问被拒: {path}", reason)
    return error_class(message or f"{method} {path} 失败: {status}")
