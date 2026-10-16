"""维表 upsert 的唯一实现。

三个采集 job 都要「按主键 upsert 一批行」，抽出来是为了让它们对
``ON CONFLICT`` 的用法保持一致 —— 各写一份迟早会有一份漏掉 ``index_elements``，
而漏掉的后果是运行时报约束冲突，且只在特定数据下才复现。
"""

from __future__ import annotations

from typing import Sequence

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession


async def upsert_all(
    session: AsyncSession,
    model,
    rows: Sequence,
    conflict: str | Sequence[str],
) -> int:
    """按主键 upsert 一批行，返回条数。

    ``conflict`` 必须是真实的唯一约束列。维表里 ``leagues.id`` 与 ``labels.id``
    在不同 kind 间会重复，所以后者要传 ``["id", "kind"]``。
    """
    if not rows:
        return 0
    columns = [c.name for c in model.__table__.columns]
    conflict_cols = [conflict] if isinstance(conflict, str) else list(conflict)
    stmt = pg_insert(model).values([{c: getattr(row, c) for c in columns} for row in rows])
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=conflict_cols,
            set_={c: getattr(stmt.excluded, c) for c in columns if c not in conflict_cols},
        )
    )
    return len(rows)