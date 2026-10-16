"""公告：列表与详情。

两条对外硬规矩：

1. **草稿绝不外泄。** 列表按 ``is_published`` 过滤；按 id 取详情**也要过滤** ——
   只过滤列表的话，用户猜 id 就能读到草稿。
2. **排序** ``is_pinned DESC, published_at DESC NULLS LAST``。
   ``NULLS LAST`` 不能省：PostgreSQL 默认把 NULL 排最大（``DESC`` 时），
   但换个数据库默认就变 —— 没有发布时间的新公告会突然跑到最前面。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.api.schemas import DEFAULT_PAGE_SIZE, DataOut, MetaOut, clamp_page_size
from app.db.models import Announcement

router = APIRouter(prefix="/api/v1")

CATEGORY_VALUES = ("notice", "maintenance", "event")


async def _session():
    from app.db.session import new_session

    return new_session()


def _content_meta(fetched_at=None) -> MetaOut:
    """内容数据的 meta。``ttl_seconds=0`` 表示无过期概念（计划层约定）。"""
    return MetaOut(
        cache="HIT", fetched_at=fetched_at, age_seconds=None, ttl_seconds=0
    )


def _out(row: Announcement) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "body": row.body,
        "category": row.category,
        "isPinned": row.is_pinned,
        "publishedAt": row.published_at,
        "updatedAt": row.updated_at,
    }


@router.get("/announcements", response_model=None)
async def list_announcements(
    category: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1),
):
    if category is not None and category not in CATEGORY_VALUES:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_PARAMS",
                "message": f"category 必须是 {list(CATEGORY_VALUES)} 之一",
            },
        )

    limit = clamp_page_size(page_size)
    session = await _session()
    try:
        # 草稿过滤在**查询里**，不是取回来再筛 —— 后者会把草稿的 id 与时间
        # 带进排序与分页，导致页码错位
        stmt = select(Announcement).where(Announcement.is_published.is_(True))
        if category is not None:
            stmt = stmt.where(Announcement.category == category)

        total = (
            await session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        rows = (
            await session.execute(
                stmt.order_by(
                    Announcement.is_pinned.desc(),
                    # 显式 NULLS LAST：不写的话各数据库默认不同，
                    # 没有发布时间的新公告可能突然排到最前面
                    Announcement.published_at.desc().nulls_last(),
                    Announcement.id.desc(),
                )
                .offset((page - 1) * limit)
                .limit(limit)
            )
        ).scalars().all()
    finally:
        await session.close()

    return DataOut(
        data={"items": [_out(r) for r in rows], "total": total},
        meta=_content_meta(),
    )


@router.get("/announcements/{announcement_id}", response_model=None)
async def get_announcement(announcement_id: int):
    session = await _session()
    try:
        row = (
            await session.execute(
                select(Announcement).where(
                    Announcement.id == announcement_id,
                    # 详情同样挡草稿：只挡列表的话，猜 id 就能读到草稿
                    Announcement.is_published.is_(True),
                )
            )
        ).scalar_one_or_none()
    finally:
        await session.close()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "公告不存在"},
        )
    return DataOut(data=_out(row), meta=_content_meta(row.updated_at))