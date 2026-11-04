import datetime as dt

from app.db.models import BaseLayout


def _row(**over):
    data = dict(
        title="t",
        th_level=18,
        layout_link=None,
        image_path=None,
        source_url=None,
        source_site="bilibili",
        content_hash=None,
        copy_count=0,
        is_published=True,
        created_at=dt.datetime.now(dt.UTC),
    )
    data.update(over)
    return BaseLayout(**data)


async def test_list_only_published(client, session):
    session.add_all([_row(title="published"), _row(title="draft", is_published=False)])
    await session.commit()

    resp = await client.get("/api/v1/bases")

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["total"] == 1
    assert [i["title"] for i in body["data"]["items"]] == ["published"]
    assert body["meta"]["cache"] == "HIT"


async def test_list_filters_by_th_level(client, session):
    session.add_all([_row(title="18本", th_level=18), _row(title="17本", th_level=17)])
    await session.commit()

    resp = await client.get("/api/v1/bases", params={"th_level": 18})

    assert [i["thLevel"] for i in resp.json()["data"]["items"]] == [18]


async def test_list_clamps_page_size_to_50(client, session):
    session.add_all([_row(title=f"#{i}") for i in range(51)])
    await session.commit()

    resp = await client.get("/api/v1/bases", params={"page_size": 500})

    assert resp.status_code == 200
    assert len(resp.json()["data"]["items"]) == 50


# --- Task 2: 管理员上传 ---

import base64

import pytest
from sqlalchemy import func, select

from app.api.routes import bases

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
LINK = "https://link.clashofclans.com/?action=OpenLayout&id=TH18%3AWB%3Aabc"


@pytest.fixture
def admin_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "boss")
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret-pass")


@pytest.fixture
def media_root(tmp_path, monkeypatch):
    monkeypatch.setattr(bases, "_media_root", lambda: tmp_path)
    return tmp_path


async def test_upload_requires_auth(client, admin_env, media_root):
    resp = await client.post("/api/v1/admin/bases", data={"title": "x"})
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"].startswith("Basic")


async def test_upload_rejects_when_env_empty(client, monkeypatch, media_root):
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    resp = await client.post(
        "/api/v1/admin/bases", data={"title": "x"},
        headers={"Authorization": "Basic " + base64.b64encode(b":").decode()},
    )
    assert resp.status_code == 401


async def test_upload_png_publishes(client, session, admin_env, media_root):
    resp = await client.post(
        "/api/v1/admin/bases",
        data={"title": "阵型A", "th_level": "18", "layout_link": LINK},
        files={"image": ("a.png", PNG, "image/png")},
        auth=("boss", "s3cret-pass"),
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["duplicated"] is False
    assert data["imagePath"].startswith("/media/bases/")
    assert (media_root / data["imagePath"].removeprefix("/media/")).is_file()


async def test_upload_rejects_fake_image(client, admin_env, media_root):
    resp = await client.post(
        "/api/v1/admin/bases", data={"title": "x"},
        files={"image": ("a.png", b"not an image", "image/png")},
        auth=("boss", "s3cret-pass"),
    )
    assert resp.status_code == 400


async def test_upload_rejects_oversize(client, admin_env, media_root):
    big = PNG + b"0" * (5 * 1024 * 1024)
    resp = await client.post(
        "/api/v1/admin/bases", data={"title": "x"},
        files={"image": ("a.png", big, "image/png")},
        auth=("boss", "s3cret-pass"),
    )
    assert resp.status_code == 413


async def test_upload_requires_link_or_image(client, admin_env, media_root):
    resp = await client.post(
        "/api/v1/admin/bases", data={"title": "x"}, auth=("boss", "s3cret-pass")
    )
    assert resp.status_code == 400


async def test_upload_is_idempotent(client, session, admin_env, media_root):
    files = {"image": ("a.png", PNG, "image/png")}
    data = {"title": "阵型A", "th_level": "18", "layout_link": LINK}
    first = await client.post("/api/v1/admin/bases", data=data, files=files,
                              auth=("boss", "s3cret-pass"))
    second = await client.post("/api/v1/admin/bases", data=data, files=files,
                               auth=("boss", "s3cret-pass"))
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["data"]["duplicated"] is True
    count = (await session.execute(select(func.count()).select_from(BaseLayout))).scalar_one()
    assert count == 1

# --- Task 3: 本地媒体静态服务 ---

import httpx
from fastapi import FastAPI


async def test_mount_media_serves_existing_file(tmp_path):
    (tmp_path / "x.txt").write_text("hi", encoding="utf-8")
    app = FastAPI()
    bases.mount_media(app, tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        resp = await c.get("/media/x.txt")

    assert resp.status_code == 200 and resp.text == "hi"


async def test_mount_media_skips_missing_dir(tmp_path):
    app = FastAPI()
    bases.mount_media(app, tmp_path / "nope")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        assert (await c.get("/media/x.txt")).status_code == 404
