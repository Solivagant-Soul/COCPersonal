"""应用工厂。

三件装配在这里完成：

1. **路由前缀** —— 全部挂在 ``/api/v1`` 下（规格 §6）。
2. **``CocClient`` 单例** —— lifespan startup 时建好放 ``app.state``。
   不放模块级全局：测试里每次 ``create_app()`` 都是新实例，
   全局变量会让上一个测试的 client（连同一个令牌桶）泄漏到下一个测试。
3. **``CocError`` 处理器** —— 统一错误体（规格 §6.2）。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.deps import get_coc_client  # noqa: F401  （暴露给依赖注入使用）
from app.api.errors import coc_error_handler
from app.api.routes import (
    admin,
    clans,
    content,
    players,
    rankings,
    submissions,
    system,
    upgrade,
)
from app.coc.client import CocClient
from app.coc.devfixtures import FixtureTransport, is_placeholder_token
from app.coc.errors import CocError
from app.coc.ratelimit import MemoryRateLimiter
from app.collector.scheduler import build_scheduler, register_jobs
from app.db.session import engine
from app.config import get_settings
from app.middleware import RateLimitMiddleware

logger = logging.getLogger("coc.startup")


def _error_json(status: int, code: str, message: str) -> JSONResponse:
    """统一错误体（规格 §6.1 的形状）。"""
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "upstream_reason": None}},
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # 没有真实 Token 时给 client 注入夹具上游（开发期；见 app/coc/devfixtures.py）。
    # 走的是同一个 CocClient，只是最底层的字节来源换成 app/coc/fixtures。
    transport = (
        FixtureTransport() if is_placeholder_token(settings.coc_api_token) else None
    )
    app.state.coc_client = CocClient(
        settings.coc_api_token or "PLACEHOLDER",
        MemoryRateLimiter(rate=settings.coc_rate_limit),
        timeout=settings.coc_timeout,
        base_url=settings.coc_base_url,
        transport=transport,
    )
    logger.info(
        "CocClient ready (rate=%s/s, upstream=%s)",
        settings.coc_rate_limit,
        "fixtures" if transport is not None else "official",
    )
    # 采集调度器。同进程起（单进程一体，AGENTS.md），角色决定要不要起。
    collector = build_scheduler(settings)
    app.state.collector = collector
    if collector.should_run:
        register_jobs(collector)
        collector.scheduler.start()
        logger.info("采集调度器已启动 (app_role=%s)", settings.app_role)
    else:
        # api 角色不起调度器：多起一个就是白白消耗令牌桶
        logger.info("app_role=%s，不启动采集调度器", settings.app_role)

    try:
        yield
    finally:
        if collector.scheduler.running:
            # APScheduler 3.x 的 shutdown() 是普通方法（不是协程），不要 await
            collector.scheduler.shutdown(wait=False)
        await app.state.coc_client.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="COC Backend", lifespan=lifespan)
    settings = get_settings()

    app.add_exception_handler(CocError, coc_error_handler)

    # 限流放在最外层：在任何业务逻辑与 DB 查询之前拦下超量请求。
    # /healthz 与 /readyz 由中间件自身豁免（EXEMPT_PATHS）。
    app.add_middleware(
        RateLimitMiddleware, requests_per_minute=settings.rate_limit_per_minute
    )

    @app.exception_handler(RequestValidationError)
    async def _on_validation_error(request, exc):
        """把 pydantic 的 422 转成 400 INVALID_PARAMS。

        422 的语义是"参数形状不对"，而我们要表达的是"参数不合法"。
        错误码不同，前端分支也不同（Review Focus 第 1 条）。
        """
        code = "INVALID_PARAMS"
        for error in exc.errors():
            if any(part in ("tag",) for part in error.get("loc", [])):
                code = "INVALID_TAG"
                break
        return _error_json(
            400, code, str(exc.errors()[0].get("msg", "参数不合法"))
        )

    @app.exception_handler(StarletteHTTPException)
    async def _on_http_exception(request, exc):
        """把 HTTPException 的 detail 归一成统一错误体。

        FastAPI 对 HTTPException 默认返回 ``{"detail": ...}``，与规格 §6.1 的
        统一错误体形状不一致。detail 是 dict 时原样带 code/message，是字符串时
        包成 UNKNOWN_ERROR。
        """
        detail = exc.detail
        if isinstance(detail, dict):
            code = detail.get("code", "UNKNOWN_ERROR")
            message = detail.get("message") or str(detail)
        else:
            code = "UNKNOWN_ERROR"
            message = str(detail)
        return _error_json(exc.status_code, code, message)

    app.include_router(system.router)
    app.include_router(clans.router)
    app.include_router(players.router)
    # 排行榜放在 players 之后：/rankings/{kind} 与 /leagues/{kind} 的路径段不会与
    # 前两者冲突，但保持"资源在前、子资源在后"的顺序便于排查
    app.include_router(rankings.router)
    app.include_router(upgrade.router)
    app.include_router(content.router)
    app.include_router(submissions.router)

    # 后台。凭据只来自环境变量（ADMIN_USERNAME / ADMIN_PASSWORD），不入库。
    # 官方数据与采集表在后台全部只读或未注册，见 admin.py 的说明。
    app.state.admin = admin.build_admin(app, engine, settings)
    return app


# 模块级实例：``Dockerfile`` 的 ``CMD`` 与文档都写 ``uvicorn app.main:app``，
# 而应用是 ``create_app()`` 工厂造出来的 —— 这个赋值是那条命令的落点。
# （原 COCBack 缺这一行，因 Docker 从未在本机跑过而未被发现；Task 9 联调时暴露。）
app = create_app()
