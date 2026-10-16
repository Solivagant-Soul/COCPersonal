"""全项目共享的测试装配。

两件易踩的事，改这个文件前先读懂：

1. **环境变量必须在任何 ``app.*`` 被 import 之前写入。**``get_settings()`` 带
   ``lru_cache``，首次调用即固化。因此 ``set_test_env()`` 在模块顶层、且在 import
   app 模块之前调用；``app`` fixture 里那次只是幂等兜底。
2. **``session`` fixture 只在这里定义**（R1 裁定）。pytest 的 fixture 按「测试文件
   所在目录」向上查找，若建 ``tests/db/conftest.py``，``tests/api/`` 就看不见它 ——
   而 Task 9 / Task 13 的测试需要同时拿到 ``client`` 与 ``session``。
"""

import os
import asyncio

import httpx
import pytest
from sqlalchemy import text


def set_test_env() -> None:
    """写入测试用环境变量。用 setdefault 以尊重外部已显式设定的值。"""
    os.environ.setdefault("COC_API_TOKEN", "test-token")
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:test@localhost:5433/postgres",
    )
    # Settings 必填但无默认值；Task 1 的测试没调过 get_settings() 所以没暴露出来
    os.environ.setdefault("PUBLIC_BASE_URL", "http://testserver")


# get_settings() 带 lru_cache，务必在 import app 模块之前就位
set_test_env()

# 放在 set_test_env() 之后：app 模块在第二次读取环境变量时，它已经就位
from app.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.main import create_app  # noqa: E402



@pytest.fixture
def app():
    """每次测试新建 app。

    **必须是 function scope，不能是 session scope**：``ASGITransport(app=app)``
    在构造时即绑定当前事件循环，而 pytest-asyncio 默认**函数级**循环。session
    作用域的 app 会让第一个测试的 transport 在后续循环里被复用，报
    ``RuntimeError: Event loop is closed`` 或 ``'NoneType' has no attribute 'send'``
    （Task 9 实测：单独跑能过、连着跑才炸）。
    """
    set_test_env()
    return create_app()


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _ensure_schema() -> None:
    """保证测试库 schema 就位。

    走 ``alembic upgrade head`` 而不是 ``Base.metadata.create_all``：后者会绕过
    迁移链，让 0001 及以后的迁移永远不被测试验证——写过一次空迁移后才知道这坑。
    alembic 的 online 模式是同步的，故单独起线程跑，避免污染 pytest-asyncio 的事件循环。

    **不加"只跑一次"的缓存**：进程内加过一次，结果新增表后测试全红而缓存还拦着
    后来者，白折腾一轮。alembic 自身幂等（已应用的迁移会跳过），每次只是多几次 SELECT。
    """
    await asyncio.to_thread(_run_alembic_upgrade)


def _run_alembic_upgrade() -> None:
    import asyncio

    from alembic import command
    from alembic.config import Config
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)

    # alembic 的 online 模式自己 asyncio.run 一个事件循环跑引擎，
    # 结束后要主动 dispose，否则测试收尾会报 ResourceWarning。
    command.upgrade(cfg, "head")
    # env.py 的 connectable 已 dispose，这里兜底关掉线程内可能残留的循环
    try:
        asyncio.get_event_loop().close()
    except Exception:
        pass


async def _truncate_all() -> None:
    """单条 SQL 清空所有表。

    **必须是单条 TRUNCATE**：逐表循环会让每个测试多几十次往返，全量套件
    直接超时（Task 10 实测：从 190s 涨到 >700s）。``CASCADE`` 让外键连带清空。
    """
    names = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="session", autouse=True)
async def _schema() -> None:
    await _ensure_schema()
    yield
    await engine.dispose()


#: 请求了其中任一 fixture 的测试才会碰数据库。
#: 本套件里这是**唯一**的数据库入口 —— 已核对：没有任何测试绕过 ``session``
#: 自建 engine 或 session（``grep async_sessionmaker|create_async_engine`` 只命中 conftest）。
_DB_FIXTURES = frozenset({"session", "client", "parent_clan"})


@pytest.fixture(autouse=True)
async def _isolate(request):
    """按需隔离：**只有真的碰数据库的测试**才截断表、才销毁连接池。

    为什么必须 autouse —— **两个独立的原因**：

    1. **数据隔离**：只有请求了 ``session`` fixture 的测试才会截断表。但每个走路由的
       测试都会读写数据库（loader / persister 自建 session），于是不请求 ``session``
       的测试会读到上一个测试的残留数据。这会造成"业务错误明明该冒泡，却因为库里有
       旧行而返回 200 + STALE"这类极难定位的假绿（Task 10 实测）。
    2. **跨事件循环**：不是每个测试都用 ``session``，但每个用到的都会开连接。连接池跨
       事件循环存活会报 ``Event loop is closed`` /
       ``'NoneType' has no attribute 'send'``（pytest-asyncio 默认函数级循环）。

    **为什么必须按需**：``tests/coc`` 里的纯函数测试（``normalize_tag`` 之类）压根不碰
    数据库，却要为每个用例付一次建连 + TRUNCATE + dispose 的代价。实测每个 setup
    4.3s，全量套件直接跑不完（>700s）。按需后这部分开销归零。

    ``request.fixturenames`` 是该用例的**完整 fixture 闭包**（含间接依赖），
    所以 ``parent_clan`` 这类包了 ``session`` 的也会被算进来。
    """
    if not _DB_FIXTURES & set(request.fixturenames):
        yield
        return

    async with engine.connect():
        await _truncate_all()
    yield
    # **不要 dispose**：pyproject 已把事件循环提到会话级（R18），连接池可以安全地
    # 跨用例复用。此前每个用例都 dispose，而一次本地重连要 2.1s。


@pytest.fixture
async def session():
    """一个干净的 session。清理由上面的 autouse fixture 统一负责。"""
    from app.db.session import async_sessionmaker

    async with async_sessionmaker() as s:
        yield s
        await s.rollback()
