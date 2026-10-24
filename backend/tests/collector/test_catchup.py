"""启动时补齐过期采集。

这台服务器不是 7×24 在线：``warreport`` 的 cron 是 04:23 UTC（北京 12:23），
而机器基本只在晚上开机，于是这个 job 永远不会被触发 —— 页面表现为
"赛季榜 / 阵容一直空"，且没有任何报错。

补齐的判定规则（每条都有用例）：

1. 从没跑过 → 补。
2. 最近一次成功、且未超过该 job 的周期 → 不补。
3. 最近一次成功、但已超过周期 → 补。
4. 最近一次不是成功（partial / failed / 卡在 running）→ 补，但要有 5 分钟
   冷却，避免进程崩溃重启时把上游打成连环请求。
"""

from __future__ import annotations

import datetime as dt

from app.collector.catchup import run_catchup, stale_jobs
from app.collector.scheduler import SCHEDULE_SPEC
from app.db.models import CollectorRun

NOW = dt.datetime(2026, 10, 24, 15, 0, tzinfo=dt.UTC)


def _add_run(
    session,
    job_name: str,
    *,
    status: str = "success",
    minutes_ago: float,
) -> CollectorRun:
    started = NOW - dt.timedelta(minutes=minutes_ago)
    run = CollectorRun(
        job_name=job_name,
        started_at=started,
        # 卡在 running 的记录没有 finished_at
        finished_at=None if status == "running" else started,
        status=status,
    )
    session.add(run)
    return run


async def _seed_fresh_successes(session, *, skip: set[str] | None = None) -> None:
    """除待测 job 外，其余都刚成功过，避免干扰断言。"""
    skipped = skip or set()
    for _cron, name, _interval in SCHEDULE_SPEC:
        if name in skipped:
            continue
        _add_run(session, name, minutes_ago=1)
    await session.commit()


async def test_never_run_jobs_are_all_stale(session):
    assert await stale_jobs(session, now=NOW) == [name for _, name, _ in SCHEDULE_SPEC]


async def test_fresh_success_is_not_stale(session):
    await _seed_fresh_successes(session)

    assert await stale_jobs(session, now=NOW) == []


async def test_success_older_than_its_interval_is_stale(session):
    await _seed_fresh_successes(session, skip={"rankings"})
    # rankings 的周期是 6 小时（21600s）
    _add_run(session, "rankings", minutes_ago=7 * 60)
    await session.commit()

    assert await stale_jobs(session, now=NOW) == ["rankings"]


async def test_failed_run_is_stale_after_cooldown(session):
    """失败也要补：用户修好 Token 后重启，不该再等一个完整周期。"""
    await _seed_fresh_successes(session, skip={"rankings"})
    _add_run(session, "rankings", status="failed", minutes_ago=10)
    await session.commit()

    assert await stale_jobs(session, now=NOW) == ["rankings"]


async def test_recent_failed_run_is_not_stale_during_cooldown(session):
    """崩溃重启时不能连环打上游 —— 最近 5 分钟内失败过就先等一等。"""
    await _seed_fresh_successes(session, skip={"rankings"})
    _add_run(session, "rankings", status="failed", minutes_ago=1)
    await session.commit()

    assert await stale_jobs(session, now=NOW) == []


async def test_interrupted_running_record_is_stale_after_cooldown(session):
    """进程被 kill 会留下永远 running 的记录 —— 那正是需要补齐的状态。"""
    await _seed_fresh_successes(session, skip={"warreport"})
    _add_run(session, "warreport", status="running", minutes_ago=30)
    await session.commit()

    assert await stale_jobs(session, now=NOW) == ["warreport"]


async def test_partial_run_is_stale(session):
    await _seed_fresh_successes(session, skip={"warreport"})
    _add_run(session, "warreport", status="partial", minutes_ago=30)
    await session.commit()

    assert await stale_jobs(session, now=NOW) == ["warreport"]


async def test_latest_run_wins_not_any_old_failure(session):
    """更早的一次失败不该让刚成功过的 job 再补一次。"""
    await _seed_fresh_successes(session, skip={"rankings"})
    _add_run(session, "rankings", status="failed", minutes_ago=30)
    await session.commit()
    _add_run(session, "rankings", status="success", minutes_ago=1)
    await session.commit()

    assert await stale_jobs(session, now=NOW) == []


async def test_run_catchup_runs_only_stale_jobs_in_schedule_order(session):
    await _seed_fresh_successes(session, skip={"rankings", "warreport"})
    _add_run(session, "rankings", minutes_ago=7 * 60)
    _add_run(session, "warreport", minutes_ago=2 * 24 * 60)
    await session.commit()

    ran: list[str] = []

    async def fake_runner(name: str) -> None:
        ran.append(name)

    names = await run_catchup(session, now=NOW, runner=fake_runner)

    # SCHEDULE_SPEC 里 rankings 在 warreport 之前 —— 保持调度顺序，
    # 也让 static_data 先跑（ranks 依赖 locations 维表）。
    assert names == ["rankings", "warreport"]
    assert ran == ["rankings", "warreport"]


async def test_run_catchup_does_nothing_when_everything_is_fresh(session):
    await _seed_fresh_successes(session)
    ran: list[str] = []

    async def fake_runner(name: str) -> None:
        ran.append(name)

    assert await run_catchup(session, now=NOW, runner=fake_runner) == []
    assert ran == []
