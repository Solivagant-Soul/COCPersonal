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
