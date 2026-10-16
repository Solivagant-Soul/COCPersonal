"""CocError → HTTP 的统一转换。

映射取值来自规格 §6.2，逐字对应 —— 前端按 ``error.code`` 做分支，
改一个值就是改前端契约。

**关于 ``CocAccessDenied → 502`` 与 Task 8 的 STALE 降级不矛盾：**
``read_through`` 在**库里有旧数据时**已经降级为 STALE 并返回 200，异常根本到不了
这里。只有**首次部署、库里一行都没有**时它才穿透上来，此时 502 是诚实的 ——
我们确实拿不到任何数据，不管是新的还是旧的。

告警不靠「禁止降级」来实现：本 handler 负责写 warning 日志（含 ``exc.reason``），
由 §7.4 的告警规则消费；而降级是缓存层的职责。两者正交。
"""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from app.api.schemas import ErrorOut
from app.coc.errors import (
    ClanNotFound,
    CocAccessDenied,

    CocError,
    CocProtocolError,
    CocThrottled,
    CocTimeout,
    CocUpstreamError,
    NotInWar,
    PlayerNotFound,
    WarLogPrivate,
)

logger = logging.getLogger("coc.api.errors")

# 异常类型 → (HTTP 状态码, 对外 error.code)
ERROR_CODE_MAP: dict[type[CocError], tuple[int, str]] = {
    ClanNotFound: (404, "CLAN_NOT_FOUND"),
    PlayerNotFound: (404, "PLAYER_NOT_FOUND"),
    NotInWar: (404, "CLAN_NOT_IN_WAR"),
    WarLogPrivate: (403, "WARLOG_PRIVATE"),
    CocThrottled: (502, "UPSTREAM_THROTTLED"),
    CocUpstreamError: (502, "UPSTREAM_UNAVAILABLE"),
    CocTimeout: (502, "UPSTREAM_UNAVAILABLE"),
    CocAccessDenied: (502, "UPSTREAM_UNAVAILABLE"),
    CocProtocolError: (502, "UPSTREAM_UNAVAILABLE"),
}


async def coc_error_handler(request: Request, exc: CocError) -> JSONResponse:
    """把 CocError 转成统一错误体。

    未收录的 ``CocError`` 子类落 ``CocBusinessError`` 基类的 400 + 一个明确的
    code，而不是 500 —— 我们认得出这是官方侧的错，只是还没细分。
    """
    status, code = ERROR_CODE_MAP.get(type(exc), (400, "COC_UNKNOWN"))

    # accessDenied.invalidIp 与其它 403 在 HTTP 层同码，但告警规则要能区分
    logger.warning(
        "coc error: %s %s -> %s (reason=%s)",
        request.method,
        request.url.path,
        code,
        exc.reason,
    )

    body = ErrorOut(
        error={
            "code": code,
            "message": str(exc) or "官方接口暂时不可用",
            "upstream_reason": exc.reason,
        }
    )
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))
