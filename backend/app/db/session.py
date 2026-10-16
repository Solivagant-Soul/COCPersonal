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
