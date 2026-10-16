"""公告：不变量与 API 行为。

两条最容易做错的：

1. **未发布公告必须对外不可见**，但后台可见 —— 草稿泄露是内容事故。
2. **置顶优先**，其次按发布时间倒序 —— 小程序首页只看前几条，
   排序错了等于公告发不出去。
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.models import Announcement

NOW = datetime.now(UTC)


@pytest.fixture
async def announcements(session):
    session.add_all([
        Announcement(title="普通一", body="x", category="notice",
                     is_published=True, published_at=NOW - timedelta(days=3),
                     created_at=NOW, updated_at=NOW),
        Announcement(title="普通二", body="x", category="notice",
                     is_published=True, published_at=NOW - timedelta(days=1),
                     created_at=NOW, updated_at=NOW),
        Announcement(title="置顶", body="x", category="notice",
                     is_published=True, is_pinned=True,
                     published_at=NOW - timedelta(days=30),
                     created_at=NOW, updated_at=NOW),
        Announcement(title="草稿", body="x", category="notice",
                     is_published=False, published_at=NOW,
                     created_at=NOW, updated_at=NOW),
    ])
    await session.commit()


# --------------------------------------------------------------------------- #
# 可见性
# --------------------------------------------------------------------------- #


async def test_unpublished_announcement_is_hidden_from_api(client, announcements):
    titles = [
        a["title"]
        for a in (await client.get("/api/v1/announcements")).json()["data"]["items"]
    ]
    assert "草稿" not in titles, "未发布公告绝不能出现在对外接口里"
    assert "置顶" in titles


async def test_unpublished_announcement_detail_is_404(client, session):
    """按 id 直取未发布公告同样要 404 —— 否则草稿等于公开了。"""
    draft = Announcement(title="草稿", body="x", category="notice",
                         is_published=False, created_at=NOW, updated_at=NOW)
    session.add(draft)
    await session.commit()

    resp = await client.get(f"/api/v1/announcements/{draft.id}")
    assert resp.status_code == 404


async def test_published_announcement_detail_is_200(client, session, announcements):
    published = (
        await session.execute(
            select(Announcement).where(Announcement.title == "普通一")
        )
    ).scalar_one()
    resp = await client.get(f"/api/v1/announcements/{published.id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["title"] == "普通一"


async def test_announcements_order_pinned_first(client, announcements):
    titles = [
        a["title"]
        for a in (await client.get("/api/v1/announcements")).json()["data"]["items"]
    ]
    assert titles[0] == "置顶", "置顶必须在首位"
    assert titles[1:] == ["普通二", "普通一"], "其余按发布时间倒序"


async def test_announcements_filters_by_category(client, session):
    session.add_all([
        Announcement(title="公告", body="x", category="notice",
                     is_published=True, published_at=NOW,
                     created_at=NOW, updated_at=NOW),
        Announcement(title="维护", body="x", category="maintenance",
                     is_published=True, published_at=NOW,
                     created_at=NOW, updated_at=NOW),
    ])
    await session.commit()

    body = (await client.get("/api/v1/announcements?category=maintenance")).json()
    assert [a["title"] for a in body["data"]["items"]] == ["维护"]


async def test_announcements_empty_returns_empty_list(client):
    body = (await client.get("/api/v1/announcements")).json()
    assert body["data"]["items"] == []


async def test_announcement_detail_404_when_missing(client):
    resp = await client.get("/api/v1/announcements/99999")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


# --------------------------------------------------------------------------- #
# 数据不变量
# --------------------------------------------------------------------------- #


async def test_announcement_published_at_is_timestamptz(session):
    """naive datetime 在大陆服务器上会让"按时间排序"偏差 8 小时。"""
    a = Announcement(title="x", body="y", category="notice",
                     is_published=True, published_at=NOW,
                     created_at=NOW, updated_at=NOW)
    session.add(a)
    await session.commit()
    loaded = await session.get(Announcement, a.id)
    assert loaded.published_at.tzinfo is not None


async def test_announcement_title_is_required(session):
    from sqlalchemy.exc import IntegrityError

    a = Announcement(body="x", category="notice", is_published=True,
                     created_at=NOW, updated_at=NOW)
    session.add(a)
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_announcement_published_at_may_be_null(session):
    """发布时间可空：草稿还没到发布时间。"""
    a = Announcement(title="x", body="y", category="notice",
                     is_published=True, published_at=None,
                     created_at=NOW, updated_at=NOW)
    session.add(a)
    await session.commit()
    assert (await session.get(Announcement, a.id)).published_at is None


async def test_announcement_null_published_at_sorts_last(client, session):
    """没有发布时间的排最后 —— 不能让它因为 NULL 而跑到最前面。"""
    session.add_all([
        Announcement(title="无时间", body="x", category="notice",
                     is_published=True, published_at=None,
                     created_at=NOW, updated_at=NOW),
        Announcement(title="有时间", body="x", category="notice",
                     is_published=True, published_at=NOW - timedelta(days=1),
                     created_at=NOW, updated_at=NOW),
    ])
    await session.commit()
    titles = [
        a["title"]
        for a in (await client.get("/api/v1/announcements")).json()["data"]["items"]
    ]
    assert titles == ["有时间", "无时间"]


# --------------------------------------------------------------------------- #
# 契约
# --------------------------------------------------------------------------- #


async def test_announcements_use_the_unified_envelope(client, announcements):
    body = (await client.get("/api/v1/announcements")).json()
    assert set(body) == {"data", "meta"}
    assert set(body["meta"]) == {"cache", "fetched_at", "age_seconds", "ttl_seconds"}
    assert body["meta"]["ttl_seconds"] == 0, "内容数据无过期概念"


async def test_announcements_page_size_is_capped(client, announcements):
    resp = await client.get("/api/v1/announcements?page_size=500")
    assert resp.status_code == 200, "超限应截断为 50 而不是 422"


async def test_announcements_page_beyond_end_returns_empty(client, announcements):
    resp = await client.get("/api/v1/announcements?page=99")
    assert resp.status_code == 200
    assert resp.json()["data"]["items"] == []


async def test_announcements_reject_unknown_category(client):
    resp = await client.get("/api/v1/announcements?category=nonsense")
    assert resp.status_code == 400