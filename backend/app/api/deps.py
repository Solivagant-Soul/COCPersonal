"""FastAPI 依赖注入。

``get_coc_client`` 由 lifespan 在 startup 时构造单例。这样做的理由：``CocClient``
内含一个 ``httpx.AsyncClient``（连接池）与共享的令牌桶 —— 每个请求各建一个的话，
令牌桶就形同虚设（各桶互不知情，总速率会超标）。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Request

from app.coc.client import CocClient
from app.coc.ratelimit import MemoryRateLimiter
from app.config import get_settings


async def get_coc_client(request: Request) -> AsyncGenerator[CocClient, None]:
    """从 ``app.state`` 取 lifespan 建好的单例；没有则惰性建一个。

    为什么要惰性：测试用 ``httpx.ASGITransport`` 直接调 ASGI app，**不触发
    lifespan**，``app.state.coc_client`` 根本不存在（Task 9 实测踩到）。
    生产走 uvicorn 时 lifespan 一定先跑，所以这条路径只是兜底。

    放 ``app.state`` 而不是模块级全局：测试里每次 ``create_app()`` 都是新实例，
    全局变量会让上一个测试的 client（连同一个令牌桶）泄漏到下一个测试。
    """
    client = getattr(request.app.state, "coc_client", None)
    if client is None:
        settings = get_settings()
        client = CocClient(
            settings.coc_api_token,
            MemoryRateLimiter(rate=settings.coc_rate_limit),
            timeout=settings.coc_timeout,
            base_url=settings.coc_base_url,
        )
        request.app.state.coc_client = client
    yield client
