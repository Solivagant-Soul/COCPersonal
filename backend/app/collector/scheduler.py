"""APScheduler 装配。

**不 import FastAPI**（AGENTS.md 架构边界）：``APP_ROLE=collector`` 时本模块要能
脱离 HTTP 层单独起进程。

角色门控是这里唯一值得注意的逻辑。``APP_ROLE`` 拼错**必须响亮地失败** ——
静默跳过意味着这个部署永远不会采集，而没有任何一行日志说明原因。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings

logger = logging.getLogger("coc.collector")

#: 允许的角色。``all`` 一体，``api`` 只服务 HTTP，``collector`` 只采集。
VALID_ROLES = frozenset({"all", "api", "collector"})

#: (cron, job 名, 间隔秒)。**cron 必须错开整点** —— 官方在整点压力最大，
#: 全部挤在 ``0 * * * *`` 会在同一秒发起几十个请求，吃掉令牌桶并大概率被限流。
#: 注意 rankings 用的是 ``"13 */6 * * *"`` 而不是 ``"13 0/6 * * *"``：
#: ``*/6`` 在 cron 里展开成 ``0,6,12,18``，**含第 0 分钟**，也就是每小时都会在
#: 整点跑一次 —— 正好是这条规则要避免的。想表达"每 6 小时且错开整点"，必须
#: 写成 ``13 */6 * * *``（错的是我第一次写成这样才对）之外的形式时，请先想清楚
#: 分钟字段到底展开成哪几个值。
#: 每条 cron 的分钟字段都**错开整点**（17 / 13 / 41 / 29 / 23）。
#:
#: rankings 是 ``13 */6 * * *``：分钟固定 13，小时每 6 小时一次。**不要**把它
#: 写成 ``*/6`` 分钟 —— 那是"每 6 分钟"，一天 240 次，官方会直接限流。
SCHEDULE_SPEC: list[tuple[str, str, int]] = [
    ("17 3 * * *", "static_data", 86400),
    ("13 */6 * * *", "rankings", 21600),
    ("41 * * * *", "leagues", 3600),
    ("29 * * * *", "seasons", 3600),
    # War Report 是第三方 API（不带 Token），但同样错开整点；每天一次足够 ——
    # 上游快照 28 天才出一份。
    ("23 4 * * *", "warreport", 86400),
]

#: 这些角色要跑调度器。``api`` 明确排除：多起一个调度器就是白白消耗令牌桶。
_COLLECTING_ROLES = frozenset({"all", "collector"})


@dataclass
class CollectorScheduler:
    """带角色门控的调度器包装。

    多包一层是为了让"要不要跑"这件事在**构造时**就有答案，而不是等到
    ``start()`` 才发现 —— 后者会让 lifespan 的测试必须真的起一个调度器。
    """

    scheduler: AsyncIOScheduler
    should_run: bool
    role: str


def build_scheduler(settings: Settings) -> CollectorScheduler:
    """按角色构造调度器。角色非法时抛 ``ValueError``。"""
    role = settings.app_role
    if role not in VALID_ROLES:
        raise ValueError(
            f"app_role 非法: {role!r}，必须是 {sorted(VALID_ROLES)} 之一"
        )

    scheduler = AsyncIOScheduler(timezone="UTC")
    return CollectorScheduler(
        scheduler=scheduler,
        should_run=role in _COLLECTING_ROLES,
        role=role,
    )


def register_jobs(collector: CollectorScheduler) -> CollectorScheduler:
    """把 :data:`SCHEDULE_SPEC` 挂到调度器上。

    每个 job 触发时自己开 session 与客户端（官方 ``CocClient`` 或 War Report
    客户端，由 ``run_job`` 按 job 名选）—— 调度器在应用 lifespan 之外
    活着，没有一个"当前 session"可依赖。``run_job`` 不收 ``client`` 时会自建。
    """
    from app.collector.service import run_job

    async def _fire(name: str) -> None:
        await run_job(name)

    for cron, name, interval in SCHEDULE_SPEC:
        collector.scheduler.add_job(
            _fire,
            trigger=CronTrigger.from_crontab(cron, timezone="UTC"),
            args=[name],
            id=name,
            name=name,
            # jitter：抵消累积漂移，避免多个 job 的请求撞在一起打爆令牌桶
            jitter=min(interval // 10, 60),
            replace_existing=True,
            # 上一次没跑完就跳过这一次，而不是排队堆叠
            max_instances=1,
            coalesce=True,
        )
        logger.info("job %s scheduled: cron=%s interval=%ss", name, cron, interval)
    return collector