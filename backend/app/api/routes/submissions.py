"""投稿接口。

**完全开放（无鉴权）** —— 小程序用户直接提交，所以校验必须在服务端做足。

刻意**不提供公开列表**：投稿是后台的工作队列，公开列表等于让任何人翻看
所有人的投稿。要看列表请走 `/admin`（Task 19）。
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.api.schemas import DataOut, MetaOut
from app.content.submissions import SubmissionStatus, SubmissionType
from app.db.models import Submission

router = APIRouter(prefix="/api/v1")

MAX_TITLE = 100


async def _session():
    from app.db.session import new_session

    return new_session()


def _bad(message: str) -> HTTPException:
    return HTTPException(
        status_code=400, detail={"code": "INVALID_PARAMS", "message": message}
    )


def _validate(payload: dict) -> None:
    """服务端校验。投稿接口无鉴权，这里是唯一的内容闸门。"""
    if not isinstance(payload, dict):
        raise _bad("请求体必须是对象")

    type_ = payload.get("type")
    if type_ not in {t.value for t in SubmissionType}:
        raise _bad(f"type 必须是 {[t.value for t in SubmissionType]} 之一")

    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        raise _bad("title 不能为空")
    if len(title) > MAX_TITLE:
        # 上限与 submissions.title 列宽一致，放行更长的话入库会报
        # StringDataRightTruncation，那是 500 而不是 400
        raise _bad(f"title 不能超过 {MAX_TITLE} 字")

    body = payload.get("payload")
    if not isinstance(body, dict):
        raise _bad("payload 必须是对象")

    if type_ == SubmissionType.army_composition:
        items = body.get("items")
        if not isinstance(items, list):
            raise _bad("payload.items 必须是数组")
        if not items:
            raise _bad("payload.items 不能为空，空阵容没有意义")
        th = body.get("th_level")
        if not isinstance(th, int):
            raise _bad("payload.th_level 必须是整数")
    else:
        if not (body.get("layout_link") or body.get("image_path")):
            raise _bad("阵型投稿必须提供 layout_link 或 image_path 至少一个")


def _out(row: Submission) -> dict:
    """投稿的对外形状。

    **不暴露** ``reviewed_by`` / ``reviewed_at`` / ``reject_reason`` ——
    那是后台内部字段，公开了等于告诉投稿者"谁在审你"。
    """
    return {
        "id": row.id,
        "type": row.type,
        "title": row.title,
        "payload": row.payload,
        "status": row.status,
        "createdAt": row.created_at,
    }


@router.post("/submissions", response_model=None, status_code=201)
async def create_submission(request: Request):
    raw = await request.json()
    _validate(raw)

    session = await _session()
    try:
        now = dt.datetime.now(dt.UTC)
        sub = Submission(
            type=raw["type"],
            title=raw["title"].strip(),
            payload=raw["payload"],
            # 显式写 pending：列上的 server_default 是给绕过 ORM 的路径兜底的，
            # 应用层自己也要给
            status=SubmissionStatus.pending.value,
            created_at=now,
        )
        session.add(sub)
        await session.commit()
        await session.refresh(sub)
        payload = _out(sub)
    finally:
        await session.close()

    return DataOut(
        data=payload,
        meta=MetaOut(cache="MISS", fetched_at=None, age_seconds=None, ttl_seconds=0),
    )


@router.get("/submissions/{submission_id}", response_model=None)
async def get_submission(submission_id: int):
    session = await _session()
    try:
        row = (
            await session.execute(
                select(Submission).where(Submission.id == submission_id)
            )
        ).scalar_one_or_none()
    finally:
        await session.close()

    if row is None:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": "投稿不存在"}
        )
    return DataOut(
        data=_out(row),
        meta=MetaOut(
            cache="HIT",
            fetched_at=row.created_at,
            age_seconds=None,
            ttl_seconds=0,
        ),
    )