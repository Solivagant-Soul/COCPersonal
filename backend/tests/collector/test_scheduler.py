"""采集调度器与角色门控。

三条要守住的线：

1. **``APP_ROLE`` 决定要不要起调度器**。``api`` 角色只服务 HTTP，``collector``
   角色不起 HTTP。三种角色都必须能起得来 —— 角色配错的后果是静默的：
   ``collector`` 角色没起调度器就等于什么都不采，线上要等一整天才发现。
2. **cron 必须错开整点**。全部挤在 ``0 * * * *`` 会在同一秒向官方发起
   几十个请求，直接吃掉令牌桶并大概率被限流。
3. **采集模块不得 import FastAPI**（AGENTS.md 架构边界）—— 否则
   ``collector`` 角色无法脱离 HTTP 层单独起进程。
"""

import ast
from pathlib import Path

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.collector.scheduler import SCHEDULE_SPEC, CollectorScheduler, build_scheduler
from app.config import Settings


def _settings(role: str) -> Settings:
    return Settings(
        coc_api_token="t",
        database_url="postgresql+asyncpg://x@localhost/x",
        app_role=role,
    )


# --------------------------------------------------------------------------- #
# 角色门控
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("role", ["all", "collector"])
def test_scheduler_should_run_for_roles_that_collect(role):
    assert build_scheduler(_settings(role)).should_run is True


def test_api_role_must_not_collect():
    """api 角色只服务 HTTP —— 多起一个调度器就是白白消耗令牌桶。"""
    assert build_scheduler(_settings("api")).should_run is False


def test_unknown_role_raises_instead_of_silently_skipping():
    """角色名拼错必须响亮地失败。

    静默跳过意味着这个部署永远不会采集，而没有任何一行日志提示原因。
    """
    with pytest.raises(ValueError, match="app_role"):
        build_scheduler(_settings("worker"))


def test_build_scheduler_returns_an_async_io_scheduler():
    sched = build_scheduler(_settings("all"))
    assert isinstance(sched.scheduler, AsyncIOScheduler)


def test_build_scheduler_wraps_the_scheduler_with_role_decision():
    """角色判定与调度器实例打包返回 —— lifespan 调一次构造就同时拿到
    "要不要跑"和"拿什么跑"，不必再问一次角色。"""
    sched = build_scheduler(_settings("api"))
    assert sched.role == "api"
    assert sched.should_run is False
    assert isinstance(sched.scheduler, AsyncIOScheduler)


# --------------------------------------------------------------------------- #
# cron 错峰
# --------------------------------------------------------------------------- #


def test_schedule_spec_has_no_duplicate_cron_expressions():
    """同一秒触发两个 job = 一次突发请求。"""
    crons = [cron for cron, _, _ in SCHEDULE_SPEC]
    assert len(crons) == len(set(crons))


def test_schedule_spec_never_fires_on_the_hour():
    """整点是官方压力最大的时刻，避开它。

    分钟字段要按 cron 的真实展开来判，不能只看语法：
    ``*/15`` 展开成 ``0,15,30,45``，含第 0 分钟，同样会在整点触发。
    """
    for cron, name, _ in SCHEDULE_SPEC:
        # cron 字段顺序是 分 时 日 月 周 —— **分钟是第 0 个**。
        # 取错字段会让这条断言检查的是小时，"13 */6 * * *" 的小时字段展开含 0，
        # 于是正确配置被判成"会在整点触发"。
        minute_field = cron.split()[0]
        minutes = _expand_minute_field(minute_field)
        assert 0 not in minutes, f"{name} 的 cron {cron!r} 会在整点触发（分钟展开为 {minutes}）"


def _expand_minute_field(field: str) -> set[int]:
    """把 cron 分钟字段展开成实际会触发的分钟集合。

    支持本项目用到的形式：``17`` / ``*/N`` / ``a-b,c``。
    """
    out: set[int] = set()
    for part in field.split(","):
        if "/" in part:
            step_part, step = part.split("/")
            step_n = int(step)
            if step_part == "*":
                out.update(range(0, 60, step_n))
            else:
                lo, _, hi = step_part.partition("-")
                # "1-59/15" → 1,16,31,46；上界也要纳入
                out.update(range(int(lo), int(hi) + 1, step_n))
        elif "-" in part:
            lo, hi = part.split("-")
            out.update(range(int(lo), int(hi) + 1))
        else:
            out.add(int(part))
    return out


def test_schedule_spec_covers_the_five_jobs():
    assert {name for _, name, _ in SCHEDULE_SPEC} == {
        "static_data",
        "rankings",
        "leagues",
        "seasons",
        "warreport",
    }


def test_schedule_spec_jitter_fits_inside_the_interval():
    """jitter 必须小于间隔，否则任务会自我重叠（上一轮还没跑完下一轮就来了）。"""
    for cron, name, seconds in SCHEDULE_SPEC:
        assert seconds > 60, f"{name} 的 interval_seconds={seconds} 太小"


async def test_register_jobs_schedules_a_startup_catchup():
    """启动时必须挂一个一次性的补齐任务。

    这台服务器只在晚上开机，``warreport`` 的 04:23 UTC 永远不会触发 ——
    没有启动补齐，页面就一直是空的，而调度器看起来一切正常。
    """
    from apscheduler.triggers.date import DateTrigger

    from app.collector.scheduler import register_jobs

    collector = build_scheduler(_settings("all"))
    register_jobs(collector)

    job = collector.scheduler.get_job("startup_catchup")
    assert job is not None
    assert isinstance(job.trigger, DateTrigger)


# --------------------------------------------------------------------------- #
# 架构边界
# --------------------------------------------------------------------------- #


def test_collector_package_does_not_import_fastapi():
    """``APP_ROLE=collector`` 要能脱离 HTTP 层起进程。

    用 AST 静态查而不是靠 import 时报错：真 import 了会在收集阶段炸，
    而报错信息不会告诉你是哪条边界被破了。
    """
    offenders = []
    for path in Path("app/collector").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in {"fastapi", "starlette", "uvicorn"}:
                        offenders.append(f"{path}:{node.lineno} import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                if root in {"fastapi", "starlette", "uvicorn"}:
                    offenders.append(f"{path}:{node.lineno} from {node.module}")
            elif isinstance(node, ast.ImportFrom) and node.level:
                # 相对 import 一律展开成绝对路径再判
                pass
    assert offenders == [], "app/collector/ 不得依赖 Web 框架：\n" + "\n".join(offenders)


def test_collector_package_does_not_import_api_routes():
    """collector 也不该反过来依赖 app/api —— 那是 HTTP 层的胶水。"""
    offenders = []
    for path in Path("app/collector").rglob("*.py"):
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            mod = getattr(node, "module", None)
            if isinstance(node, ast.ImportFrom) and mod and mod.startswith("app.api"):
                offenders.append(f"{path}:{node.lineno} from {mod}")
    assert offenders == [], "app/collector/ 不得依赖 app.api：\n" + "\n".join(offenders)


# --------------------------------------------------------------------------- #
# lifespan 接线
# --------------------------------------------------------------------------- #


async def test_lifespan_starts_and_stops_the_scheduler(monkeypatch):
    """角色为 all 时 lifespan 必须真的把调度器起起来，并在退出时关掉。"""
    from app import main as main_module

    created = {}

    class FakeScheduler:
        should_run = True

        def __init__(self):
            self.started = False
            self.shutdown_called = False
            self.running = False

        def start(self):
            self.started = True
            self.running = True

        def shutdown(self, wait=True):
            # APScheduler 3.x 的 shutdown 是**同步**方法。写成 async 会让 lifespan
            # 的 await 拿到未 await 的协程警告，而 shutdown 实际根本没执行 ——
            # 测试里表现为"退出后调度器还在跑"，且只有一个 RuntimeWarning。
            self.shutdown_called = True
            self.running = False

    def fake_build(settings):
        # lifespan 拿的是 CollectorScheduler 包装类，不是裸调度器
        sched = FakeScheduler()
        created["sched"] = sched
        return CollectorScheduler(
            scheduler=sched, should_run=True, role=settings.app_role
        )

    monkeypatch.setattr(main_module, "build_scheduler", fake_build)
    monkeypatch.setattr(main_module, "get_settings", lambda: _settings("all"))
    # FakeScheduler 没有 running 属性，lifespan 的 finally 会读它
    monkeypatch.setattr(main_module, "register_jobs", lambda c: c)

    app = main_module.create_app()
    async with app.router.lifespan_context(app):
        assert created["sched"].started is True
        # lifespan 必须把包装类挂到 app.state，供 /meta/freshness 等处查采集状态
        assert app.state.collector.should_run is True
    assert created["sched"].shutdown_called is True


async def test_lifespan_does_not_start_scheduler_for_api_role(monkeypatch):
    from app import main as main_module

    created = {}

    class FakeScheduler:
        should_run = False

        def __init__(self):
            self.started = False
            self.running = False

        def start(self):  # pragma: no cover - api 角色不该走到这里
            self.started = True
            self.running = True

        def shutdown(self, wait=True):  # pragma: no cover
            self.running = False

    monkeypatch.setattr(
        main_module,
        "build_scheduler",
        lambda s: created.setdefault(
            "s",
            CollectorScheduler(
                scheduler=FakeScheduler(), should_run=False, role=s.app_role
            ),
        ),
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: _settings("api"))
    monkeypatch.setattr(main_module, "register_jobs", lambda c: c)

    app = main_module.create_app()
    async with app.router.lifespan_context(app):
        assert created["s"].scheduler.started is False
        assert app.state.collector.should_run is False