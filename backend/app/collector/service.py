"""采集 job 编排：统一的运行记录 + 状态判定。

每个 job 的外壳完全一样，所以抽在这里：**只要接进 :data:`JOBS` 就自动获得
运行留痕与部分失败记账**，新写一个 job 不需要重写这些。

状态语义（``RunStatus``）：

- ``running``  正在干活。**先落库再干活**，进程被 kill 时库里会留下一条永远
  不结束的记录 —— 那正是"卡住了"的唯一信号。
- ``success``  全部成功。
- ``partial``  一部分成功一部分失败。**必须如实记账**：笼统记成 success 会让
  "某个地区的榜单缺了一半"永远没人发现。
- ``failed``   一个都没成功。
"""

from __future__ import annotations

import datetime as dt
import logging
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.coc.client import CocClient
from app.collector.jobs.leagues import collect_leagues
from app.collector.jobs.rankings import collect_rankings
from app.collector.jobs.seasons import collect_seasons
from app.collector.jobs.static_data import collect_static_data
from app.collector.jobs.warreport import collect_warreport
from app.db.models import CollectorRun

if TYPE_CHECKING:
    # 只为类型检查：``from __future__ import annotations`` 让注解不在导入期求值，
    # 真正的客户端实现由 ``run_job`` 在自建客户端时按 job 名 import。
    from app.warreport.client import WarReportClient

logger = logging.getLogger("coc.collector")

#: 截断到多少字符再入库。异常消息可能带着整个响应体。
_MAX_ERROR_CHARS = 2000


class RunStatus(StrEnum):
    running = "running"
    success = "success"
    partial = "partial"
    failed = "failed"


#: job 名 → 实现。键即 :data:`app.collector.scheduler.SCHEDULE_SPEC` 里的名字。
#:
#: 客户端与返回形状都不统一（官方采集用 ``CocClient``、War Report 用
#: ``WarReportClient``），所以标注写成 ``Any`` 的入参 + ``Any`` 的返回：
#: 各 job 自己的统计口径不同，由 :func:`_summarize` 收敛。
JOBS: dict[str, Callable[[Any, AsyncSession], Awaitable[dict[str, Any]]]] = {
    "static_data": collect_static_data,
    "rankings": collect_rankings,
    "leagues": collect_leagues,
    "seasons": collect_seasons,
    "warreport": collect_warreport,
}


def _summarize(result: dict[str, Any]) -> tuple[int, int]:
    """把各 job 各自的返回形状收敛成 ``(ok, failed)``。

    各 job 的统计口径本来就不一样（维表报"写了几行"，榜单报"几个 scope 成功"），
    但运行记录只有一对 ok/failed 字段，所以在这里统一。
    """
    if "items_failed" in result:
        return int(result.get("items_ok", 0)), int(result.get("items_failed", 0))
    # 维表类 job 只有"写了几条"，没有失败概念
    return sum(int(v) for v in result.values()), 0


async def run_job(
    job_name: str,
    settings: Any = None,
    session: AsyncSession | None = None,
    *,
    client: CocClient | WarReportClient | None = None,
) -> str:
    """跑一个采集 job，返回最终 status。

    ``session`` / ``client`` 不传时自建 —— 调度器触发时没有任何"当前上下文"，
    只能自己开。测试则传进来复用同一套 fixture。

    job 名不存在时抛 ``KeyError``：拼错必须响亮失败，不能静默跳过，
    否则这个采集永远不会发生而没人知道。
    """
    if job_name not in JOBS:
        raise KeyError(
            f"未知的采集 job: {job_name!r}，可选 {sorted(JOBS)}"
        )

    owns_session = session is None
    owns_client = client is None
    if owns_session:
        from app.db.session import async_sessionmaker

        session = async_sessionmaker()
        session = await session.__aenter__()
    if owns_client:
        from app.config import get_settings
        from app.coc.ratelimit import MemoryRateLimiter

        effective = settings or get_settings()
        if job_name == "warreport":
            # 上游是第三方只读 API（warreport.app），没有令牌桶也没有 key ——
            # 拿 CocClient 去打它只会 401/404。
            from app.warreport.client import client_from_settings

            client = client_from_settings(effective)
        else:
            client = CocClient(
                effective.coc_api_token,
                MemoryRateLimiter(rate=effective.coc_rate_limit),
                timeout=effective.coc_timeout,
                base_url=effective.coc_base_url,
            )

    now = dt.datetime.now(dt.UTC)
    run = CollectorRun(
        job_name=job_name,
        started_at=now,
        status=RunStatus.running.value,
    )
    session.add(run)
    # 立即提交：干活之前就让这条记录落库。进程被 kill 时它会永远停在
    # running —— 那正是"卡住了"的信号。
    await session.commit()
    run_id = run.id

    try:
        result = await JOBS[job_name](client, session)
        ok, failed = _summarize(result)
        status = _decide(ok, failed)
        error = None
        if failed:
            # 带上 job 自己收集的失败明细。只写"失败了 N 个"的话，线上得翻日志
            # 才知道是哪个地区出的问题。
            detail = result.get("detail")
            error = {"failed": failed, "detail": detail or f"{failed} 个 scope 失败"}
        total = ok + failed
    except Exception as exc:  # noqa: BLE001 - job 的任何异常都要留痕，不能让调度器崩
        logger.exception("采集 job %s 失败", job_name)
        ok, failed, total = 0, 1, 1
        status = RunStatus.failed
        error = {
            "type": type(exc).__name__,
            "detail": str(exc)[:_MAX_ERROR_CHARS],
        }
        # 必须先 rollback：job 与本函数共用同一个 session，DB 层抛的错会让事务进入
        # aborted 状态。不回滚的话下面那条 UPDATE collector_runs 会以
        # InFailedSQLTransactionError 失败 —— 于是**连失败记录都写不进去**，
        # 而这正是最需要留痕的时刻。
        await session.rollback()
        # 回滚后 run 实例已失效（expire_on_commit），重新取一次
        run = await session.get(CollectorRun, run_id)

    run.status = status.value
    run.finished_at = dt.datetime.now(dt.UTC)
    run.items_total = total
    run.items_ok = ok
    run.items_failed = failed
    run.error = error
    await session.commit()
    logger.info(
        "采集 job %s -> %s (ok=%s failed=%s)", job_name, status.value, ok, failed
    )

    if owns_client:
        await client.aclose()
    if owns_session:
        await session.__aexit__(None, None, None)
    return status.value


def _decide(ok: int, failed: int) -> RunStatus:
    """按 ok/failed 判定状态。**部分成功必须是 partial**，不能笼统记 success。"""
    if failed and ok:
        return RunStatus.partial
    if failed:
        return RunStatus.failed
    return RunStatus.success