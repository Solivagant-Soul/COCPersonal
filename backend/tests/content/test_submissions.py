"""投稿：审核流转的业务规则。

审核是这套系统里**唯一会创建正式内容**的路径，所以规则必须硬：

1. **只能审核 pending。** 重复审核必须报错，否则后台连点两下就产生两份内容。
2. **单事务。** 建内容与回填状态要么都成，要么都不成 ——
   半途失败会留下一条"已审核"但查不到内容的投稿。
3. **同内容去重。** ``content_hash`` 让同一个人重复提交同一份内容
   不会产生两份正式记录。
"""

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.content.submissions import (
    SubmissionStatus,
    SubmissionType,
    approve_submission,
    compute_content_hash,
)
from app.db.models import (
    ArmyComposition,
    ArmyCompositionItem,
    BaseLayout,
    Submission,
)

NOW = datetime.now(UTC)


def _payload(th: int = 16) -> dict:
    return {
        "th_level": th,
        "items": [
            {"category": "troop", "name": "Hog Rider", "quantity": 30, "level": 14}
        ],
    }


def _layout_payload() -> dict:
    return {"th_level": 16, "layout_link": "https://example.com/layout/1"}


async def _pending(session, type_="army_composition", payload=None) -> Submission:
    sub = Submission(
        type=type_,
        title="TH16猪流",
        payload=payload if payload is not None else _payload(),
        status=SubmissionStatus.pending.value,
        created_at=NOW,
    )
    session.add(sub)
    await session.commit()
    return sub


# --------------------------------------------------------------------------- #
# 审核：内容类
# --------------------------------------------------------------------------- #


async def test_approve_creates_army_composition_and_items(session):
    sub = await _pending(session)
    result = await approve_submission(session, sub)

    assert isinstance(result, ArmyComposition)
    assert result.th_level == 16
    assert result.source_site == "user_submission"

    items = (
        await session.execute(
            select(ArmyCompositionItem).where(
                ArmyCompositionItem.composition_id == result.id
            )
        )
    ).scalars().all()
    assert len(items) == 1
    assert items[0].name == "Hog Rider"
    assert items[0].quantity == 30

    assert sub.status == SubmissionStatus.approved.value
    assert sub.reviewed_at is not None


async def test_approve_sets_content_hash(session):
    sub = await _pending(session)
    result = await approve_submission(session, sub)
    assert result.content_hash == compute_content_hash(
        sub.type, sub.title, sub.payload
    )
    assert len(result.content_hash) == 64, "应为 sha256 的十六进制长度"


async def test_approve_creates_base_layout(session):
    sub = await _pending(session, "base_layout", _layout_payload())
    result = await approve_submission(session, sub)
    assert isinstance(result, BaseLayout)
    assert result.th_level == 16


# --------------------------------------------------------------------------- #
# 审核：幂等与非法状态
# --------------------------------------------------------------------------- #


async def test_approve_submission_twice_does_not_duplicate(session):
    """后台连点两下"通过"，不能产生两份内容。"""
    sub = await _pending(session)
    await approve_submission(session, sub)

    with pytest.raises(ValueError):
        await approve_submission(session, sub)

    count = (
        await session.execute(select(func.count()).select_from(ArmyComposition))
    ).scalar_one()
    assert count == 1


async def test_approve_rejects_rejected_submission(session):
    sub = await _pending(session)
    sub.status = SubmissionStatus.rejected.value
    await session.commit()

    with pytest.raises(ValueError):
        await approve_submission(session, sub)


async def test_approve_rejects_unknown_type(session):
    sub = await _pending(session, "something_else", {})
    with pytest.raises(ValueError):
        await approve_submission(session, sub)
    assert (
        await session.execute(select(func.count()).select_from(ArmyComposition))
    ).scalar_one() == 0


async def test_approve_rejects_empty_items(session):
    """空阵容无意义，审核时也要挡 —— 后台不该成为绕过 POST 校验的后门。"""
    sub = await _pending(session, "army_composition", {"th_level": 16, "items": []})
    with pytest.raises(ValueError):
        await approve_submission(session, sub)


async def test_approve_rolls_back_on_failure(session):
    """建内容失败时不能留下"已审核"但没有内容的投稿。"""
    sub = await _pending(session, "army_composition", {"th_level": 16, "items": []})
    with pytest.raises(ValueError):
        await approve_submission(session, sub)

    await session.rollback()
    stored = await session.get(Submission, sub.id)
    assert stored.status == SubmissionStatus.pending.value, (
        "审核失败后投稿必须仍是 pending，否则这条内容就永久消失了"
    )


# --------------------------------------------------------------------------- #
# content_hash
# --------------------------------------------------------------------------- #


def test_content_hash_is_stable_across_key_order():
    """payload 的键顺序不同但内容相同，hash 必须一致 ——
    否则同一个人改个字段顺序就能绕过去重，产生重复内容。"""
    a = {"th_level": 16, "items": [{"name": "Hog Rider", "quantity": 30}]}
    b = {"items": [{"quantity": 30, "name": "Hog Rider"}], "th_level": 16}
    assert compute_content_hash("t", "标题", a) == compute_content_hash("t", "标题", b)


def test_content_hash_differs_on_content_change():
    a = compute_content_hash("t", "标题", {"th": 16})
    b = compute_content_hash("t", "标题", {"th": 17})
    assert a != b


def test_content_hash_is_not_ambiguous_across_fields():
    """拼接时分隔，避免 ('ab','c') 与 ('a','bc') 撞出同一个 hash。"""
    assert compute_content_hash("ab", "c", {}) != compute_content_hash("a", "bc", {})


# --------------------------------------------------------------------------- #
# 状态机取值
# --------------------------------------------------------------------------- #


def test_submission_status_values():
    assert {s.value for s in SubmissionStatus} == {
        "pending",
        "approved",
        "rejected",
    }


def test_submission_type_values():
    assert {t.value for t in SubmissionType} == {
        "army_composition",
        "base_layout",
    }


async def test_submission_defaults_to_pending(session):
    """默认状态必须是 pending 且必须落库 —— 靠应用层默认值而列无 DEFAULT 时，
    直接插 SQL 的路径会拿到 NULL。"""
    sub = Submission(type="army_composition", title="x", payload={},
                     created_at=NOW)
    session.add(sub)
    await session.commit()
    assert sub.status == "pending"


async def test_submission_payload_roundtrips_as_jsonb(session):
    sub = await _pending(session, "army_composition", _payload(17))
    await session.refresh(sub)
    assert sub.payload["th_level"] == 17
    assert isinstance(sub.payload["items"], list)


async def test_submission_payload_requires_matching_type(session):
    """JSONB 不校验形状，但 ArmyComposition 里存的必须是 dict 而不是标量。"""
    sub = await _pending(session, "army_composition", {"th_level": 16, "items": "垃圾"})
    with pytest.raises(ValueError):
        await approve_submission(session, sub)
    assert json.dumps(sub.payload)  # 原始数据仍可读，审核只是拒绝