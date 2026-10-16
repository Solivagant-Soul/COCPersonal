"""对外 IP 限流。

进程内实现（单进程一体，AGENTS.md）：``dict[str, list[float]]`` 记每个客户端 IP
的请求时间戳，滑动窗口内计数。

三个容易做错的地方：

1. **``/healthz`` 与 ``/readyz`` 必须豁免。** 容器编排器会高频调这两个端点，
   不豁免的话服务会被自己的健康检查打死 —— 表现为"服务好好的但一直不健康"。
2. **必须认 ``X-Forwarded-For`` 的第一个值。** nginx 反代后
   ``request.client.host`` 永远是 ``127.0.0.1``；不认这个头的话全网用户共用
   一个桶，一个人刷爆所有人被限。
3. **滑动窗口，不是固定窗口。** 固定窗口会在窗口边界把额度一次性翻倍
   （59 秒用完 60 次，跨过整分钟后又能立刻用 60 次）。

**只保护对外 API，不保护静态文件与探针。** 上游是微信小程序，没有静态资源。

将来要多进程时，把 :class:`RateLimitMiddleware.allow` 换成 Redis 原子操作即可，
接口不用变 —— 这就是 AGENTS.md 说的"``RateLimiter`` 接口现在就用"。
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Callable

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("coc.ratelimit")

#: 不计入限流桶的路径前缀。容器探针必须能无限调用。
EXEMPT_PATHS = frozenset({"/healthz", "/readyz"})

#: 限流窗口（秒）。
WINDOW_SECONDS = 60.0


def _client_ip(request: Request) -> str:
    """取真实客户端 IP。

    **优先 ``X-Forwarded-For`` 的第一个值**：那是 nginx
    ``$proxy_add_x_forwarded_for`` 写下的原始客户端地址。之后才是 peer 地址。
    取不到时返回空串 —— 拿不到身份的请求共用一个桶，比崩溃好。
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    client = request.client
    return client.host if client else ""


class RateLimitMiddleware(BaseHTTPMiddleware):
    """每 IP 每分钟 N 次的固定内存限流。

    :param requests_per_minute: 窗口内允许的请求数
    :param clock: 取当前时间的函数，测试里可注入以免真等 60 秒
    """

    def __init__(
        self,
        app,
        requests_per_minute: int = 60,
        clock: Callable[[], float] | None = None,
    ) -> None:
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._clock = clock or time.time
        self._last_purge = self._clock()

    def now(self) -> float:
        return self._clock()

    # -- 内部 ------------------------------------------------------------- #

    def _purge(self) -> None:
        """清掉窗口外的记录。

        不清的话内存随见过的 IP 数无限增长 —— 一个用代理轮换 IP 的客户端
        就能把进程内存吃光。
        """
        cutoff = self.now() - WINDOW_SECONDS
        for ip in [ip for ip, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
            del self._hits[ip]
        self._last_purge = self.now()

    async def allow(self, request: Request) -> bool:
        """这条请求是否放行。"""
        if self.now() - self._last_purge >= WINDOW_SECONDS:
            self._purge()

        ip = _client_ip(request)
        cutoff = self.now() - WINDOW_SECONDS
        # 先丢掉窗口外的，再看还剩几个
        hits = [t for t in self._hits[ip] if t > cutoff]
        self._hits[ip] = hits

        if len(hits) >= self.requests_per_minute:
            return False
        hits.append(self.now())
        return True

    # -- 中间件 ---------------------------------------------------------- #

    async def dispatch(self, request: Request, call_next):
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        if not await self.allow(request):
            # 最早的那次请求滑出窗口还要多久 —— 那时才会空出额度
            oldest = self._hits[_client_ip(request)][0]
            retry_after = int(WINDOW_SECONDS - (self.now() - oldest))
            logger.warning("限流触发: %s %s", request.method, request.url.path)
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": f"请求过于频繁，每分钟最多 "
                        f"{self.requests_per_minute} 次",
                        "upstream_reason": None,
                    }
                },
                headers={"Retry-After": str(max(1, retry_after))},
            )

        return await call_next(request)


class _Request:
    """测试用的最小 Request 替身。

    只实现 ``headers.get`` 与 ``client.host`` —— 限流逻辑真正用到的东西。
    构造真的 ``Request`` 需要完整的 ASGI scope 与 receive 通道，比这个麻烦得多，
    而测不出更多东西。
    """

    def __init__(self, scope: dict) -> None:
        self.scope = scope
        raw = scope.get("headers") or []
        self.headers = {
            key.decode().lower(): value.decode() for key, value in raw
        }

        class _Client:
            host = None

        client = scope.get("client")
        if client:
            _Client.host = client[0]
        self.client = _Client() if client else None