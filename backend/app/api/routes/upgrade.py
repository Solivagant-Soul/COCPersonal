"""升级条目与升级路线查询。

**只读库，不回源** —— 内容数据来自 npm 数据集（Task 15 导入），不经
read_through：没有回源、没有过期、也没有官方 API 的失败模式。

内容类 ``meta`` 的约定（**计划层补全，不是规格原文**）：规格 §6.1 只定义了官方
数据的 HIT/MISS/STALE，没定义内容数据。取 ``ttl_seconds=0`` 作为"这是内容不是
官方数据"的标志 —— 前端判这个值即可，不需要额外的类型字段。

非法 ``category`` / ``village`` 返 **400 INVALID_PARAMS 而非 404**：路由存在，
是取值域不对。这与 ``list_leagues`` 的处理一致。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.schemas import DEFAULT_PAGE_SIZE, DataOut, MetaOut, clamp_page_size
from app.db.models import UpgradeItem, UpgradeRoute, UpgradeRouteStep

router = APIRouter(prefix="/api/v1")

CATEGORY_VALUES = ("building", "troop", "spell", "hero", "equipment")
VILLAGE_VALUES = ("home", "builderBase")


async def _session():
    from app.db.session import new_session

    return new_session()


def _content_meta(fetched_at=None) -> MetaOut:
    """内容数据的 meta。``ttl_seconds=0`` 表明"无过期概念"。"""
    return MetaOut(
        cache="HIT",
        fetched_at=fetched_at,
        age_seconds=None,
        ttl_seconds=0,
    )


def _invalid(field: str, allowed) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "code": "INVALID_PARAMS",
            "message": f"{field} 必须是 {list(allowed)} 之一",
        },
    )


def _item_out(row: UpgradeItem) -> dict:
    return {
        "id": row.id,
        "category": row.category,
        "name": row.name,
        "nameZh": row.name_zh,
        "village": row.village,
        # level 的语义是"从 level 升到 level+1"，与导入层一致
        "level": row.level,
        "gold": row.gold,
        "elixir": row.elixir,
        "darkElixir": row.dark_elixir,
        "buildTimeSeconds": row.build_time_seconds,
        "builderCount": row.builder_count,
        "requiredTownhallLevel": row.required_townhall_level,
        "requiredLabLevel": row.required_lab_level,
        "requiredBuilderBaseLevel": row.required_builder_base_level,
        "notes": row.notes,
    }


@router.get("/upgrade/items", response_model=None)
async def list_items(
    category: str | None = Query(default=None),
    village: str | None = Query(default=None),
    name: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1),
):
    if category is not None and category not in CATEGORY_VALUES:
        raise _invalid("category", CATEGORY_VALUES)
    if village is not None and village not in VILLAGE_VALUES:
        raise _invalid("village", VILLAGE_VALUES)

    limit = clamp_page_size(page_size)
    session = await _session()
    try:
        stmt = select(UpgradeItem)
        if category is not None:
            stmt = stmt.where(UpgradeItem.category == category)
        if village is not None:
            stmt = stmt.where(UpgradeItem.village == village)
        if name is not None:
            stmt = stmt.where(UpgradeItem.name == name)

        total = (
            await session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        # 排序必须稳定：翻页时靠 (name, level) 定位，
        # 只按 id 排的话同名条目在不同页的顺序可能变，用户会看到重复或遗漏
        rows = (
            await session.execute(
                stmt.order_by(UpgradeItem.name, UpgradeItem.level, UpgradeItem.id)
                .offset((page - 1) * limit)
                .limit(limit)
            )
        ).scalars().all()
    finally:
        await session.close()

    return DataOut(
        data={"items": [_item_out(r) for r in rows], "total": total},
        meta=_content_meta(),
    )


def _route_out(row: UpgradeRoute) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "nameZh": row.name_zh,
        "description": row.description,
        "createdAt": row.created_at,
    }


def _step_out(row: UpgradeRouteStep) -> dict:
    return {
        "id": row.id,
        "stepOrder": row.step_order,
        "targetLevel": row.target_level,
        "notes": row.notes,
        # item 为空是合法的：步骤可以只写文字说明（如"先升级实验室"）
        "item": _item_out(row.item) if row.item is not None else None,
    }


@router.get("/upgrade/routes", response_model=None)
async def list_routes(
    from_th: int | None = Query(default=None, ge=1),
    to_th: int | None = Query(default=None, ge=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1),
):
    """列路线。``from_th`` / ``to_th`` 按步骤的目标大营等级筛。"""
    limit = clamp_page_size(page_size)
    session = await _session()
    try:
        stmt = select(UpgradeRoute)
        if from_th is not None or to_th is not None:
            # 用子查询筛"存在符合条件的步骤"的路线：筛步骤本身没有意义，
            # 用户问的是"这个路线能不能在大营 N 时用"
            step_cond = select(UpgradeRouteStep.route_id)
            if from_th is not None:
                step_cond = step_cond.where(
                    UpgradeRouteStep.target_level >= from_th
                )
            if to_th is not None:
                step_cond = step_cond.where(
                    UpgradeRouteStep.target_level <= to_th
                )
            stmt = stmt.where(UpgradeRoute.id.in_(step_cond))

        total = (
            await session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        rows = (
            await session.execute(
                stmt.order_by(UpgradeRoute.id.desc())
                .offset((page - 1) * limit)
                .limit(limit)
            )
        ).scalars().all()
    finally:
        await session.close()

    return DataOut(
        data={"items": [_route_out(r) for r in rows], "total": total},
        meta=_content_meta(),
    )


@router.get("/upgrade/routes/{route_id}", response_model=None)
async def get_route(route_id: int):
    session = await _session()
    try:
        row = (
            await session.execute(
                select(UpgradeRoute)
                .where(UpgradeRoute.id == route_id)
                # selectinload 一次取回步骤与条目，省掉 N+1：
                # 一条路线几十步，懒加载会打几十次库
                .options(
                    selectinload(UpgradeRoute.steps).selectinload(
                        UpgradeRouteStep.item
                    )
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(
                status_code=404, detail={"code": "NOT_FOUND", "message": "路线不存在"}
            )
        payload = _route_out(row)
        payload["steps"] = [
            _step_out(s) for s in sorted(row.steps, key=lambda s: s.step_order)
        ]
    finally:
        await session.close()

    return DataOut(data=payload, meta=_content_meta())