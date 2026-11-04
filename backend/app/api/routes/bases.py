"""阵型（基地布局）路由。

对外只暴露**已发布**的阵型；草稿与未审内容一律不出现在列表里。
图片由 `media` 卷承载，库里只存 `/media/...` 相对 URL，具体托管见
`docs/deployment.md` §15。
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.schemas import DEFAULT_PAGE_SIZE, DataOut, MetaOut, clamp_page_size
from app.db.models import BaseLayout

router = APIRouter(prefix="/api/v1")


def base_layout_out(row: BaseLayout) -> dict[str, object]:
    """单条阵型的对外形状（camelCase）。"""
    return {
        "id": row.id,
        "title": row.title,
        "thLevel": row.th_level,
        "layoutLink": row.layout_link,
        "imagePath": row.image_path,
        "sourceUrl": row.source_url,
        "sourceSite": row.source_site,
        "createdAt": row.created_at,
    }


def _meta() -> MetaOut:
    """内容型数据没有上游回源，`ttl_seconds=0`。"""
    return MetaOut(cache="HIT", fetched_at=None, age_seconds=None, ttl_seconds=0)


@router.get("/bases", response_model=None)
async def list_bases(
    th_level: int | None = Query(default=None, ge=1, le=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1),
):
    from app.db.session import new_session

    limit = clamp_page_size(page_size)
    stmt = select(BaseLayout).where(BaseLayout.is_published.is_(True))
    if th_level is not None:
        stmt = stmt.where(BaseLayout.th_level == th_level)

    session = new_session()
    try:
        total = (
            await session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        rows = (
            (
                await session.execute(
                    stmt.order_by(
                        BaseLayout.created_at.desc(), BaseLayout.id.desc()
                    )
                    .offset((page - 1) * limit)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    finally:
        await session.close()

    return DataOut(
        data={"items": [base_layout_out(row) for row in rows], "total": total},
        meta=_meta(),
    )
