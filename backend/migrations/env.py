"""Alembic 环境。

URL 从 ``Settings`` 读而不是 ``alembic.ini`` 的 ``sqlalchemy.url``：本项目的配置
唯一来源是环境变量（``app.config``），ini 里留空。

异步写法：引擎是 asyncpg 的，因此用 ``asyncengine.run_sync()`` 跑同步的
migration 函数，而不是把 URL 改成同步驱动 —— 后者要求额外装 psycopg2。
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings

# 关键：必须先 import 模型，把它们注册到 Base.metadata，否则 autogenerate
# 会"成功"地生成一个空迁移——这是 alembic 最经典的静默陷阱。
# 新增模型时不需要改这里，app.db.models 是唯一注册点。
from app.db import models as _models  # noqa: F401  (注册 ORM 类)
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def do_run_migrations(connection: object) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        {"sqlalchemy.url": config.get_main_option("sqlalchemy.url")},
        prefix="sqlalchemy.",
    )

    async def _run() -> None:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
        await connectable.dispose()

    asyncio.run(_run())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
