"""启动时补齐过期采集任务。

**为什么需要这一层**：``SCHEDULE_SPEC`` 是纯 cron 的，错过一次就等下一个周期。
部署在只在晚上开机的机器上时，``warreport`` 的 ``23 4 * * *``（UTC，即北京
12:23）几乎永远不会落在开机窗口里 —— 页面表现是「赛季榜 / 阵容一直空」，
而调度器、接口、上游全都正常，``collector_runs`` 里连一条失败记录都没有。

补齐规则（每条都有对应测试）：

* 从没跑过 → 补；
* 最近一次成功且未超过该 job 的周期 → 不补；
* 最近一次成功但已超过周期 → 补；
* 最近一次不是成功（``partial`` / ``failed`` / 卡在 ``running``）→ 补，
  但受 :data:`RETRY_COOLDOWN_SECONDS` 冷却约束，避免崩溃重启连环打上游。

**只按周期判，不按"数据表是否为空"判**：job 自己的返回形状差异很大，
用 ``collector_runs`` 这一张表统一判断才不用为每个 job 写一套探针。
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collector.scheduler import SCHEDULE_SPEC
from app.collector.service import RunStatus, run_job
from app.db.models import CollectorRun

logger = logging.getLogger("coc.collector.catchup")

#: 非成功运行后的冷却时间。进程崩溃重启时，5 分钟内不重复补，避免把上游
#: 打成连环请求；正常配置错误修复后重启，等冷却过去即可（通常远小于一个周期）。
RETRY_COOLDOWN_SECONDS = 300


async def stale_jobs(
    session: AsyncSession, *, now: dt.datetime | None = None
) -> list[str]:
    """按 :data:`SCHEDULE_SPEC` 的顺序返回需要补跑的 job 名。"""
    now = now or dt.datetime.now(dt.UTC)
    stale: list[str] = []

    for _cron, name, interval in SCHEDULE_SPEC:
        row = (
            await session.execute(
                select(
                    CollectorRun.status,
                    CollectorRun.started_at,
                    CollectorRun.finished_at,
                )
                .where(CollectorRun.job_name == name)
                # 按**时间**取最近一次，不按自增 id：手工补数/时钟回拨时两者
                # 可能不一致，而"最近一次运行"的语义是时间。
                .order_by(CollectorRun.started_at.desc(), CollectorRun.id.desc())
                .limit(1)
            )
        ).first()

        if row is None:
            stale.append(name)
            continue

        status, started_at, finished_at = row
        # 卡在 running 的记录没有 finished_at：用 started_at 判断冷却，
        # 冷却一过就认为该轮已经中断、需要重跑。
        last_attempt = finished_at or started_at
        # TIMESTAMPTZ 正常是 aware；这里兜底，避免手工插的裸时间让减法抛
        # ``can't subtract offset-naive and offset-aware datetimes``。
        if last_attempt.tzinfo is None:
            last_attempt = last_attempt.replace(tzinfo=dt.UTC)
        age = (now - last_attempt).total_seconds()

        if age < RETRY_COOLDOWN_SECONDS:
            continue
        if status != RunStatus.success.value:
            stale.append(name)
            continue
        if age >= interval:
            stale.append(name)

    return stale


async def run_catchup(
    session: AsyncSession,
    *,
    now: dt.datetime | None = None,
    runner=None,
) -> list[str]:
    """补齐过期 job，返回实际补跑的 job 名（保持调度表顺序）。

    ``runner`` 只给测试注入；生产走 :func:`app.collector.service.run_job`。
    **逐个 await**，不并发 —— 和调度器一样，串行才不会一起撞令牌桶。
    """
    names = await stale_jobs(session, now=now)
    if not names:
        return []

    logger.info("启动补齐：%s", ", ".join(names))
    run = runner or run_job
    for name in names:
        await run(name)
    return names
