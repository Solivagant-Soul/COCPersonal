"""投稿：类型、状态与审核流转。

审核是这套系统里**唯一会创建正式内容**的路径，所以规则必须硬：

1. **只能审核 pending。** 后台连点两下"通过"不能产生两份内容 ——
   ``ValueError`` 而不是静默幂等，因为静默会让"我明明只点了一次"变成谜题。
2. **单事务。** 建内容与回填状态要么都成、要么都不成。半途失败会留下一条
   "已审核"但查不到内容的投稿，这条内容就**永久消失了**。
3. **``content_hash`` 用规范化 JSON。** 键顺序不同但内容相同的投稿必须同 hash，
   否则改个字段顺序就能绕过去重。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ArmyComposition,
    ArmyCompositionItem,
    BaseLayout,
    Submission,
)


class SubmissionType(StrEnum):
    army_composition = "army_composition"
    base_layout = "base_layout"


class SubmissionStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


def compute_content_hash(
    type_: str, title: str, payload: dict, source_site: str = "user_submission"
) -> str:
    """内容哈希。

    **用规范化 JSON**（``sort_keys=True``）而不是字符串拼接：拼接时分隔符
    处理不当会让 ``("ab", "c")`` 与 ``("a", "bc")`` 撞出同一个 hash，而那在
    去重逻辑里意味着两种不同内容被当成一份。
    """
    canonical = json.dumps(
        {"type": type_, "title": title, "payload": payload, "site": source_site},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _require_items(payload: dict) -> list[dict]:
    items = payload.get("items")
    # 必须是**非空**数组。空阵容对用户没有意义，放进去只会污染审核队列。
    if not isinstance(items, list) or not items:
        raise ValueError("payload.items 必须是非空数组")
    return items


async def approve_submission(
    session: AsyncSession,
    submission: Submission,
    reviewer: str | None = None,
):
    """把一条待审投稿转成正式内容，返回创建出来的记录。

    单事务内完成：建内容 → 建子项 → 回填投稿状态。任何一步失败都整体回滚。

    重复审核抛 ``ValueError``：后台点两下不该产生两份内容，而「静默返回已有的
    那份」更难排查 —— 管理员会以为自己点了两次就存了两份。
    """
    if submission.status != SubmissionStatus.pending:
        raise ValueError(
            f"只能审核 pending 的投稿，当前状态: {submission.status}"
        )

    if submission.type == SubmissionType.army_composition:
        # 必须 await —— 漏掉的话 result 是个 coroutine，
        # 而报错要等到调用方访问属性时才炸，现象是"'coroutine' object has no
        # attribute 'xxx'"，完全指不到是漏了 await
        result = await _build_army_composition(session, submission)
    elif submission.type == SubmissionType.base_layout:
        result = await _build_base_layout(session, submission)
    else:
        raise ValueError(f"未知的投稿类型: {submission.type}")

    submission.status = SubmissionStatus.approved
    submission.reviewed_at = dt.datetime.now(dt.UTC)
    submission.reviewed_by = reviewer
    session.add(submission)
    await session.flush()
    return result


async def _build_army_composition(session: AsyncSession, sub: Submission) -> ArmyComposition:
    payload = sub.payload
    items = _require_items(payload)
    th_level = payload.get("th_level")
    if not isinstance(th_level, int):
        raise ValueError("payload.th_level 必须是整数")

    content_hash = compute_content_hash(sub.type, sub.title, payload)
    composition = ArmyComposition(
        title=sub.title,
        title_zh=payload.get("title_zh"),
        description=payload.get("description"),
        th_level=th_level,
        source_url=payload.get("source_url"),
        # 固定标记来源，便于日后按"用户投稿"筛选
        source_site="user_submission",
        content_hash=content_hash,
        copy_count=0,
        # 投稿不自动发布：内容要人工确认后才对外可见
        is_published=False,
        submission_id=sub.id,
        created_at=dt.datetime.now(dt.UTC),
    )
    session.add(composition)
    await session.flush()

    for position, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"payload.items[{position}] 必须是对象")
        name = item.get("name")
        if not name or not isinstance(name, str):
            raise ValueError(f"payload.items[{position}].name 必须是非空字符串")
        session.add(
            ArmyCompositionItem(
                composition_id=composition.id,
                position=position,
                category=item.get("category"),
                name=name,
                level=item.get("level"),
                quantity=item.get("quantity"),
                notes=item.get("notes"),
            )
        )
    await session.flush()
    return composition


async def _build_base_layout(session: AsyncSession, sub: Submission) -> BaseLayout:
    payload = sub.payload
    # 阵型必须给链接或图片至少一个 —— 两个都没有的"阵型"没有任何内容
    if not (payload.get("layout_link") or payload.get("image_path")):
        raise ValueError("阵型投稿必须提供 layout_link 或 image_path 至少一个")

    th_level = payload.get("th_level")
    layout = BaseLayout(
        title=sub.title,
        title_zh=payload.get("title_zh"),
        description=payload.get("description"),
        th_level=th_level if isinstance(th_level, int) else None,
        layout_link=payload.get("layout_link"),
        image_path=payload.get("image_path"),
        source_url=payload.get("source_url"),
        source_site="user_submission",
        content_hash=compute_content_hash(sub.type, sub.title, payload),
        copy_count=0,
        is_published=False,
        submission_id=sub.id,
        created_at=dt.datetime.now(dt.UTC),
    )
    session.add(layout)
    await session.flush()
    return layout