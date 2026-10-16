"""升级条目与升级路线查询接口。

这些路由**只读库，不回源** —— 内容数据不经 read_through（无回源、无过期）。

内容类 ``meta`` 的约定（计划层补全，非规格原文）：规格 §6.1 只定义了官方数据的
三种缓存态，没定义内容数据。取 ``cache="HIT"``、``ttl_seconds=0`` ——
前端判 ``ttl_seconds == 0`` 即可区分内容与官方数据。
"""

from datetime import UTC, datetime

import pytest

from app.db.models import UpgradeItem, UpgradeRoute, UpgradeRouteStep

NOW = datetime.now(UTC)


@pytest.fixture
async def items(session):
    session.add_all([
        UpgradeItem(category="hero", name="Barbarian King", village="home",
                    level=1, dark_elixir=20000, build_time_seconds=3600,
                    required_townhall_level=5),
        UpgradeItem(category="hero", name="Barbarian King", village="home",
                    level=2, dark_elixir=30000, build_time_seconds=7200,
                    required_townhall_level=5),
        UpgradeItem(category="troop", name="Hog Rider", village="home",
                    level=1, elixir=10000, build_time_seconds=1800,
                    required_townhall_level=5),
        UpgradeItem(category="troop", name="Hog Rider", village="builderBase",
                    level=1, elixir=20000, required_builder_base_level=3),
        UpgradeItem(category="spell", name="Poison", village="home",
                    level=1, dark_elixir=1000, required_lab_level=3),
        UpgradeItem(category="equipment", name="Inferno Sword", village="home",
                    level=1, gold=5000),
    ])
    await session.commit()


@pytest.fixture
async def routes(session):
    route = UpgradeRoute(name="TH16 hog rush", name_zh="TH16 猪流",
                         description="先莽猪人再带球", created_at=NOW)
    session.add(route)
    await session.commit()

    session.add_all([
        UpgradeRouteStep(route_id=route.id, step_order=1, item_id=None,
                         target_level=5, notes="升级实验室"),
        UpgradeRouteStep(route_id=route.id, step_order=2, item_id=None,
                         target_level=6, notes="升级大营"),
    ])
    await session.commit()
    return route


# --------------------------------------------------------------------------- #
# 条目查询
# --------------------------------------------------------------------------- #


async def test_upgrade_items_filters_by_category(client, items):
    """``data`` 是 ``{"items": [...], "total": n}``，不是裸数组。"""
    resp = await client.get("/api/v1/upgrade/items?category=hero")
    assert resp.status_code == 200
    rows = resp.json()["data"]["items"]
    assert all(i["category"] == "hero" for i in rows)
    assert len(rows) == 2


async def test_upgrade_items_filters_by_village(client, items):
    resp = await client.get("/api/v1/upgrade/items?village=builderBase")
    assert [i["name"] for i in resp.json()["data"]["items"]] == ["Hog Rider"]


async def test_upgrade_items_filters_by_name(client, items):
    resp = await client.get("/api/v1/upgrade/items?name=Hog%20Rider")
    assert len(resp.json()["data"]["items"]) == 2, "同名条目在两个村各一行，都要返回"


async def test_upgrade_items_combines_filters(client, items):
    body = (
        await client.get("/api/v1/upgrade/items?category=troop&village=home")
    ).json()
    assert [i["village"] for i in body["data"]["items"]] == ["home"]


async def test_upgrade_items_empty_table_returns_empty_list_not_error(client):
    """表空是正常状态（导入还没跑），不是错误。"""
    resp = await client.get("/api/v1/upgrade/items?category=troop")
    assert resp.status_code == 200
    assert resp.json()["data"]["items"] == []


async def test_upgrade_items_rejects_invalid_category(client):
    resp = await client.get("/api/v1/upgrade/items?category=nonexistent")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMS"


async def test_upgrade_items_rejects_invalid_village(client):
    resp = await client.get("/api/v1/upgrade/items?village=mars")
    assert resp.status_code == 400


async def test_upgrade_items_returns_total(client, items):
    body = (await client.get("/api/v1/upgrade/items")).json()
    assert body["data"]["total"] == 6


async def test_upgrade_items_orders_by_name_then_level(client, items):
    body = (await client.get("/api/v1/upgrade/items")).json()
    keys = [(i["name"], i["level"]) for i in body["data"]["items"]]
    assert keys == sorted(keys), "排序要稳定，否则翻页会漏条目"


async def test_upgrade_items_exposes_cost_and_requirements(client, items):
    body = (await client.get("/api/v1/upgrade/items?category=spell")).json()
    row = body["data"]["items"][0]
    assert row["darkElixir"] == 1000
    assert row["requiredLabLevel"] == 3
    assert row["gold"] is None
    assert row["elixir"] is None


async def test_upgrade_items_exposes_builder_base_level(client, items):
    body = (await client.get("/api/v1/upgrade/items?village=builderBase")).json()
    assert body["data"]["items"][0]["requiredBuilderBaseLevel"] == 3


async def test_upgrade_items_exposes_name_zh_when_filled(client, session):
    session.add(UpgradeItem(category="troop", name="Barbarian", village="home",
                            level=1, elixir=1000, name_zh="野蛮人"))
    await session.commit()
    body = (await client.get("/api/v1/upgrade/items?name=Barbarian")).json()
    assert body["data"]["items"][0]["nameZh"] == "野蛮人"


async def test_upgrade_items_page_size_is_capped_at_50(client, items):
    """超限截断为 50，不是 422（AGENTS.md 硬规矩）。"""
    resp = await client.get("/api/v1/upgrade/items?page_size=500")
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 6


async def test_upgrade_items_page_beyond_end_returns_empty(client, items):
    resp = await client.get("/api/v1/upgrade/items?page=99")
    assert resp.status_code == 200
    assert resp.json()["data"]["items"] == []


async def test_upgrade_items_page_size_zero_returns_400(client, items):
    resp = await client.get("/api/v1/upgrade/items?page_size=0")
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# 路线
# --------------------------------------------------------------------------- #


async def test_upgrade_routes_lists_routes(client, routes):
    body = (await client.get("/api/v1/upgrade/routes")).json()
    assert body["data"]["items"][0]["name"] == "TH16 hog rush"
    assert body["data"]["items"][0]["nameZh"] == "TH16 猪流"


async def test_upgrade_route_detail_includes_ordered_steps(client, routes):
    body = (await client.get(f"/api/v1/upgrade/routes/{routes.id}")).json()
    steps = body["data"]["steps"]
    assert [s["stepOrder"] for s in steps] == [1, 2], "步骤必须按 step_order 升序"
    assert steps[0]["targetLevel"] == 5
    assert steps[0]["notes"] == "升级实验室"


async def test_upgrade_route_detail_404_when_missing(client):
    resp = await client.get("/api/v1/upgrade/routes/999999")
    assert resp.status_code == 404


async def test_upgrade_route_detail_returns_not_found_code(client):
    resp = await client.get("/api/v1/upgrade/routes/999999")
    assert resp.json()["error"]["code"] == "NOT_FOUND"


async def test_upgrade_routes_filters_by_townhall_range(client, session):
    """``from_th`` / ``to_th`` 筛的是步骤的目标大营等级。"""
    low = UpgradeRoute(name="TH5 route", created_at=NOW)
    high = UpgradeRoute(name="TH16 route", created_at=NOW)
    session.add_all([low, high])
    await session.commit()
    session.add_all([
        UpgradeRouteStep(route_id=low.id, step_order=1, target_level=5),
        UpgradeRouteStep(route_id=high.id, step_order=1, target_level=16),
    ])
    await session.commit()

    body = (await client.get("/api/v1/upgrade/routes?from_th=10&to_th=20")).json()
    assert [r["name"] for r in body["data"]["items"]] == ["TH16 route"]


async def test_upgrade_route_detail_resolves_item(client, session, items):
    """步骤的 item_id 要展开成条目快照，前端不必再发一次请求。"""
    from sqlalchemy import select

    item = (
        await session.execute(
            select(UpgradeItem).where(
                UpgradeItem.name == "Hog Rider",
                UpgradeItem.level == 1,
                UpgradeItem.village == "home",
            )
        )
    ).scalars().one()
    route = UpgradeRoute(name="r", created_at=NOW)
    session.add(route)
    await session.commit()
    session.add(
        UpgradeRouteStep(route_id=route.id, step_order=1, item_id=item.id)
    )
    await session.commit()

    body = (await client.get(f"/api/v1/upgrade/routes/{route.id}")).json()
    step = body["data"]["steps"][0]
    assert step["item"]["name"] == "Hog Rider"
    assert step["item"]["level"] == 1


async def test_upgrade_route_step_without_item_returns_null(client, session):
    """步骤可以只写文字说明（``item_id`` 为空），不能因此报错。"""
    route = UpgradeRoute(name="r", created_at=NOW)
    session.add(route)
    await session.commit()
    session.add(
        UpgradeRouteStep(route_id=route.id, step_order=1, notes="只有说明")
    )
    await session.commit()

    body = (await client.get(f"/api/v1/upgrade/routes/{route.id}")).json()
    assert body["data"]["steps"][0]["item"] is None


# --------------------------------------------------------------------------- #
# 契约
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path",
    ["/api/v1/upgrade/items", "/api/v1/upgrade/routes"],
)
async def test_unified_envelope(client, path):
    body = (await client.get(path)).json()
    assert set(body) == {"data", "meta"}
    assert set(body["meta"]) == {"cache", "fetched_at", "age_seconds", "ttl_seconds"}


async def test_content_meta_marks_zero_ttl(client, items):
    """内容数据的 meta 用 ``ttl_seconds == 0`` 与官方数据区分（计划层补全）。

    官方数据有缓存与过期，内容数据没有回源也没有过期 —— 前端判这个值即可
    决定要不要显示"数据可能已过期"之类的提示。
    """
    body = (await client.get("/api/v1/upgrade/items")).json()
    assert body["meta"]["ttl_seconds"] == 0
    assert body["meta"]["cache"] in {"HIT", "MISS", "STALE"}
    assert body["meta"]["cache"] == body["meta"]["cache"].upper()


async def test_upgrade_items_never_calls_coc(client):
    """结构断言：这条路由不持有 CocClient。

    内容数据来自 npm 数据集，与 Supercell 无关。若哪天有人给它接上回源，
    这条测试会直接失败。
    """
    import inspect

    from app.api.routes import upgrade as routes

    params = inspect.signature(routes.list_items).parameters
    assert "client" not in params