"""异步引擎与 session 工厂。

引擎在模块导入时创建，因此 ``DATABASE_URL`` 必须在此之前就已写入环境 —— 这一点由
``tests/conftest.py`` 在模块顶层保证；生产环境由进程启动前的 .env / 环境变量保证。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_settings = get_settings()

engine: AsyncEngine = create_async_engine(
    _settings.database_url,
    echo=False,
    pool_pre_ping=True,
)

async_sessionmaker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：每次请求一个 session，请求结束即关闭。"""
    async with async_sessionmaker() as session:
        yield session


def new_session() -> AsyncSession:
    """新建一个独立 session（非依赖注入场景用；**调用方负责 close**）。

    不要用 ``await anext(get_session())`` 取 session：那个 async generator 永远不会
    被关闭，垃圾回收时会对已经 close 的 session 再 close 一次，日志里冒出
    ``sqlalchemy.exc.IllegalStateChangeError: Method 'close()' can't be called here``
    （Task 9 首次在真实进程里联调时暴露；测试只断言响应，看不见这条日志噪声）。
    """
    return async_sessionmaker()
