"""存活探针与就绪探针。

两个端点分工明确，别混：

- ``/healthz`` —— 进程活着吗。不查任何依赖，永不失败。
- ``/readyz`` —— 能对外服务吗。查 DB；``APP_ROLE=all`` 时还要求调度器已启动。

**两者都不计入限流桶**（AGENTS.md）：容器编排器的高频探针若被自己的限流器打死，
现象是"服务其实活着却一直不健康"，排查方向会完全跑偏。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db.session import engine

router = APIRouter()
logger = logging.getLogger("coc.system")


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """存活探针。**不查依赖** —— DB 挂了不代表进程该被重启。"""
    return {"status": "ok"}


def scheduler_ready(collector) -> bool:
    """调度器状态是否满足该角色的预期。

    ``api`` 角色本来就不采集，调度器没跑是正常的 —— 不能因此报 503，
    否则所有只服务读流量的小实例都会永久不就绪、永远拿不到流量。
    """
    if collector is None:
        return True
    if not getattr(collector, "should_run", False):
        return True
    return bool(getattr(collector.scheduler, "running", False))


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    """就绪探针。DB 不可达（或该采集却没在采集）时返回 503。"""
    db_ok = True
    try:
        # 模块级 import（不是函数内）—— 测试要能替换 engine 来模拟 DB 不可达
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - 任何失败都算"不就绪"
        logger.warning("readyz: DB 不可达: %s", exc)
        db_ok = False

    collector = getattr(request.app.state, "collector", None)
    sched_ok = scheduler_ready(collector)
    if not sched_ok:
        logger.warning("readyz: app_role=%s 但调度器未运行", getattr(collector, "role", "?"))

    ready = db_ok and sched_ok
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready"},
    )