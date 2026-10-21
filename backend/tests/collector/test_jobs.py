"""采集 job 的编排行为。

要守住的三件事：

1. **每次运行都留痕**。``CollectorRun`` 先以 ``running`` 落库再干活 —— 进程被
   kill 时数据库里会留下一条永远不结束的记录，这正是"卡住了"的唯一信号。
2. **部分失败要如实记账**。三个地区刷了两个挂一个，status 必须是 ``partial``
   且 ``items_failed=1``。笼统记成 ``success`` 会让"榜单缺了一半"这件事永远
   没人发现。
3. **采集必须幂等**。定时任务会重复跑，任何一次重复都不能让行数翻倍。

**替身按 HTTP 路径分发，不按 endpoint 函数名。** ``app.coc.endpoints`` 里的函数
是真实实现，内部调 ``client.get(path)``；按函数名分发的替身接不到这些调用，
于是 job 拿到空响应却**不报任何错** —— 采集"成功"地写了零行。踩过一次。
"""

import datetime as dt
import inspect
from datetime import UTC

import pytest
from sqlalchemy import func, select

from app.collector import service
from app.collector.jobs import rankings as rankings_job
from app.collector.rankings_service import RankingKind
from app.collector.service import run_job
from app.coc.errors import CocBusinessError, CocUpstreamError
from app.db.models import CollectorRun, League, Location, Ranking, Season


class FakeClient:
    """按请求路径分发的假客户端。

    ``routes`` 的键是**路径片段**（子串匹配，越长的键优先匹配），值可以是
    dict、要抛的异常，或 ``async def(path, params)`` 的可调用对象。
    """

    def __init__(self, routes: dict | None = None, default: dict | None = None):
        self.routes = routes or {}
        self.default = default if default is not None else {}
        self.calls: list[tuple[str, str, dict]] = []

    def _match(self, path: str):
        """精确路径 → 带尾斜杠的前缀 → 子串，三级回退。

        **必须精确优先**：``/leagues/{id}/seasons``（赛季清单，返回 ``seasons``）
        与 ``/leagues/{id}/seasons/{sid}``（赛季名次，返回 ``items``）只差一段，
        子串匹配会让短的那个被长的抢走，两个响应形状根本不同。配错的后果是
        测试以"Season 表为空"失败，而错误信息完全指不到真正的原因。
        """
        if path in self.routes:
            return self.routes[path]
        for frag in sorted(self.routes, key=len, reverse=True):
            if frag.endswith("/") and path.startswith(frag):
                return self.routes[frag]
        for frag in sorted(self.routes, key=len, reverse=True):
            if frag in path:
                return self.routes[frag]
        return self.default

    async def get(self, path: str, params: dict | None = None, **kw):
        self.calls.append(("GET", path, params or {}))
        value = self._match(path)
        if isinstance(value, Exception):
            raise value
        if callable(value):
            # 同步可调用（测试里最常见的是普通 def）也要支持 —— 只 await 协程函数的话，
            # 传进来的 def 会原样返回函数对象，报 "'function' object has no attribute
            # 'get'"，而错误信息完全指不到是替身没处理好返回值。
            result = value(path, params or {})
            if inspect.isawaitable(result):
                result = await result
            return result
        return value

    async def post(self, path: str, payload=None, **kw):
        self.calls.append(("POST", path, payload or {}))
        return self._match(path)


@pytest.fixture
def settings():
    from app.config import Settings

    return Settings(
        coc_api_token="t",
        database_url="postgresql+asyncpg://x@localhost/x",
        app_role="collector",
    )


async def _seed_locations(session, *ids: int, countries: bool = True) -> None:
    now = dt.datetime.now(UTC)
    for lid in ids:
        session.add(Location(id=lid, name=f"L{lid}", is_country=countries))
    await session.commit()


# --------------------------------------------------------------------------- #
# 静态数据
# --------------------------------------------------------------------------- #


async def test_collect_static_data_is_idempotent(session, settings):
    """连续两次，行数不翻倍。定时任务必然重复跑。"""
    client = FakeClient(
        routes={"/locations": {"items": [{"id": 1, "name": "China", "isCountry": True}]}}
    )
    await run_job("static_data", settings, session, client=client)
    first = (await session.execute(select(func.count()).select_from(Location))).scalar_one()

    await run_job("static_data", settings, session, client=client)
    second = (await session.execute(select(func.count()).select_from(Location))).scalar_one()

    assert first == 1
    assert second == 1


async def test_collect_static_data_populates_locations(session, settings):
    client = FakeClient(
        routes={
            "/locations": {
                "items": [
                    {"id": 32000001, "name": "China", "isCountry": True,
                     "countryCode": "CN"},
                    {"id": 32000000, "name": "Global", "isCountry": False},
                ]
            }
        }
    )
    await run_job("static_data", settings, session, client=client)

    rows = (await session.execute(select(Location).order_by(Location.id))).scalars().all()
    assert [r.id for r in rows] == [32000000, 32000001]
    assert rows[1].is_country is True
    assert rows[1].country_code == "CN"
    assert rows[0].country_code is None, "Global 等非国家地区官方不发这个字段"


async def test_collect_static_data_stores_label_kind(session, settings):
    """labels 表按 kind 区分 clan/player，id 在两类间可重复 —— 必须写对 kind。

    响应形状以官方为准：``{"items": [...]}``，不是 ``{"labels": [...]}``
    （2026-10-21 线上实测：按 ``labels`` 读会让这个 job 永远写 0 行却报 success）。
    """
    client = FakeClient(
        routes={
            "/labels/clans": {"items": [{"id": 1, "name": "ClanL"}]},
            "/labels/players": {"items": [{"id": 1, "name": "PlayerL"}]},
        }
    )
    await run_job("static_data", settings, session, client=client)

    from app.db.models import Label

    rows = (await session.execute(select(Label))).scalars().all()
    assert {(r.kind, r.name) for r in rows} == {("clan", "ClanL"), ("player", "PlayerL")}


async def test_collect_static_data_stores_league_tiers_with_icons(session, settings):
    """``/leaguetiers`` 的响应是 ``{"items": [...]}``，图标字段是 ``iconUrls``。

    读错键的后果不是报错，而是**表里一行都没有、job 却报 success** —— 只有断言
    行数才能抓住（2026-10-21 之前它就是读的 ``tiers``，一直写 0 行）。
    """
    client = FakeClient(
        routes={
            "/leaguetiers": {
                "items": [
                    {
                        "id": 29000020,
                        "name": "Legend League",
                        "iconUrls": {"small": "https://example.test/s.png"},
                    }
                ]
            }
        }
    )
    await run_job("static_data", settings, session, client=client)

    from app.db.models import LeagueTier

    rows = (await session.execute(select(LeagueTier))).scalars().all()
    assert [(r.id, r.name) for r in rows] == [(29000020, "Legend League")]
    assert rows[0].icon_urls == {"small": "https://example.test/s.png"}


# --------------------------------------------------------------------------- #
# 联赛
# --------------------------------------------------------------------------- #


async def test_collect_leagues_upserts_all_three_kinds(session, settings):
    """三类联赛列表的响应都是 ``{"items": [...]}``，图标字段是 ``iconUrls``。"""
    client = FakeClient(
        routes={
            "/warleagues": {
                "items": [
                    {
                        "id": 48000000,
                        "name": "Crystal League I",
                        "iconUrls": {"small": "https://example.test/w.png"},
                    }
                ]
            },
            "/capitalleagues": {"items": [{"id": 50000000, "name": "Capital League I"}]},
            "/builderbaseleagues": {
                "items": [{"id": 19000000, "name": "Builder League I"}]
            },
        }
    )
    await run_job("leagues", settings, session, client=client)
    await run_job("leagues", settings, session, client=client)

    count = (await session.execute(select(func.count()).select_from(League))).scalar_one()
    assert count == 3, "重复运行不能让联赛行数翻倍"

    rows = (await session.execute(select(League))).scalars().all()
    assert {r.kind for r in rows} == {"war", "capital", "builder_base"}
    war = next(r for r in rows if r.kind == "war")
    assert war.icon_urls == {"small": "https://example.test/w.png"}


# --------------------------------------------------------------------------- #
# 赛季：只为当前赛季抓排名
# --------------------------------------------------------------------------- #


async def test_collect_seasons_writes_season_rows_and_current_season_rankings(session, settings):
    # 联赛 id 必须是 ``/leagues`` 里的 Legend League（29000022）。另两套 id 都会被
    # 上游 400：warleague 的 48000000、``/leaguetiers`` 的 105000036（2026-10-21 实测）。
    client = FakeClient(
        routes={
            # 赛季名次与赛季清单路径只差一段，必须按完整路径配
            "/leagues/29000022/seasons/2026-09": {
                "items": [{"tag": "#P1", "name": "P1", "rank": 1}]
            },
            "/leagues/29000022/seasons": {
                "items": [{"id": "2026-09"}],
                "paging": {"cursors": {}},
            },
        }
    )
    await run_job("seasons", settings, session, client=client)

    seasons = (await session.execute(select(Season))).scalars().all()
    assert len(seasons) == 1
    assert seasons[0].league_id == 29000022
    assert seasons[0].id == "2026-09"
    # 官方赛季元素只有 id，没有 name —— 用 id 兜底，不能写成 NULL
    assert seasons[0].name == "2026-09"

    ranks = (
        await session.execute(
            select(Ranking).where(Ranking.kind == RankingKind.season_players)
        )
    ).scalars().all()
    assert len(ranks) == 1
    assert ranks[0].tag == "#P1"
    assert ranks[0].league_id == 29000022
    assert ranks[0].season_id == "2026-09"

    # warleague / leaguetier 的 id 绝不能出现在赛季接口里（上线后 400 的直接原因）
    assert all("/warleagues" not in path for _, path, _ in client.calls)
    assert all("105000036" not in path for _, path, _ in client.calls)
    # 官方默认只回 10 条，采集必须显式要满一页
    list_calls = [c for c in client.calls if c[1] == "/leagues/29000022/seasons"]
    assert list_calls[0][2] == {"limit": 50}
    player_calls = [c for c in client.calls if c[1].endswith("/seasons/2026-09")]
    assert player_calls and player_calls[0][2] == {"limit": 50}


async def test_collect_seasons_pages_to_the_latest_season(session, settings):
    """赛季清单**由旧到新**分页，当前赛季在最后一页。

    只取第一页的话会拿到 2015-07，赛季榜就永远刷在十年前 —— 而且不会报错。
    """

    def seasons(path, params):
        if params.get("after") == "cursor-1":
            return {"items": [{"id": "2026-10"}], "paging": {"cursors": {}}}
        return {
            "items": [{"id": "2015-07"}, {"id": "2015-08"}],
            "paging": {"cursors": {"after": "cursor-1"}},
        }

    client = FakeClient(
        routes={
            "/leagues/29000022/seasons/2026-10": {"items": [{"tag": "#P9", "name": "P9", "rank": 1}]},
            "/leagues/29000022/seasons": seasons,
        }
    )
    await run_job("seasons", settings, session, client=client)

    rows = (await session.execute(select(Season))).scalars().all()
    assert len(rows) == 3
    player_calls = [c for c in client.calls if c[1].endswith("/seasons/2026-10")]
    assert len(player_calls) == 1, f"只有当前赛季该抓排名，实际：{player_calls}"
    list_calls = [c for c in client.calls if c[1] == "/leagues/29000022/seasons"]
    assert len(list_calls) == 2, f"应该翻两页，实际：{list_calls}"


async def test_collect_seasons_records_failure_when_upstream_rejects_league_id(
    session, settings
):
    """上游 400 必须记成 failed，不能又是 ``success (ok=0 failed=0)``。

    2026-10-21 线上就是全 23 个 warleague 逐个 400，job 却报 success —— 因为
    当时 ``items_failed`` 只统计了赛季名次的失败，赛季清单本身的失败没记账。
    """
    client = FakeClient(
        routes={
            "/leagues/29000022/seasons": CocBusinessError(
                "Unknown value for parameter leagueId"
            )
        }
    )
    status = await run_job("seasons", settings, session, client=client)

    assert status == "failed"
    run = (
        await session.execute(select(CollectorRun).order_by(CollectorRun.id.desc()))
    ).scalars().first()
    assert run.status == "failed"
    assert run.items_ok == 0
    assert run.items_failed == 1
    assert run.error and "leagueId" in str(run.error)
    # 失败明细要指名是哪个 scope，别只剩一个数字
    assert any(
        "leagues/29000022/seasons" in str(d) for d in run.error.get("detail") or []
    )


# --------------------------------------------------------------------------- #
# 榜单：部分失败必须如实记账
# --------------------------------------------------------------------------- #


async def test_collect_rankings_records_partial_failure(session, settings):
    """三个地区、部落榜：第二个地区挂掉 → status=partial，ok/failed 如实。"""
    await _seed_locations(session, 32000001, 32000002, 32000003)

    def board(path, params):
        if "/32000002/" in path:
            raise CocUpstreamError("上游 5xx")
        loc = path.split("/locations/")[1].split("/")[0]
        return {"items": [{"tag": f"#T{loc}", "name": "X", "rank": 1}]}

    client = FakeClient(routes={"/rankings/": board})
    status = await run_job("rankings", settings, session, client=client)

    assert status == "partial"
    run = (
        await session.execute(select(CollectorRun).order_by(CollectorRun.id.desc()))
    ).scalars().first()
    assert run.status == "partial"
    # 5 类榜单 × 3 个地区 = 15 个 scope，中间那个地区的 5 类全挂
    assert run.items_failed == 5
    assert run.items_ok == 10
    assert run.error
    # 失败明细要指明是哪个地区，不能只有一个数字
    assert any("32000002" in str(d) for d in run.error["detail"])


async def test_collect_rankings_survives_db_error_in_one_scope(session, settings, monkeypatch):
    """一个 scope 落库报错，不能把整轮采集带崩。

    真实事故（2026-10-21）：两个采集进程并发写 rankings 触发死锁，job 回滚后
    循环又去读 ``location.id`` —— ORM 实例已被 rollback expire，异步会话里同步
    懒加载直接 ``MissingGreenlet``，整轮 failed，后面的地区一个都没刷。
    """
    await _seed_locations(session, 32000001, 32000002)

    real_replace = rankings_job.replace_rankings

    async def flaky(session_, kind, location_id, league_id, season_id, items, now=None):
        if location_id == 32000001 and kind == RankingKind.clans:
            raise RuntimeError("deadlock detected")
        return await real_replace(
            session_, kind, location_id, league_id, season_id, items, now=now
        )

    monkeypatch.setattr(rankings_job, "replace_rankings", flaky)
    client = FakeClient(
        routes={"/rankings/": {"items": [{"tag": "#T1", "name": "X", "rank": 1}]}}
    )
    status = await run_job("rankings", settings, session, client=client)

    assert status == "partial"
    run = (
        await session.execute(select(CollectorRun).order_by(CollectorRun.id.desc()))
    ).scalars().first()
    assert run.items_failed == 1
    assert any("32000001" in str(d) for d in run.error["detail"])
    # 挂掉的 scope 之外的都照常落库（2 地区 × 5 类 − 1）
    rows = (await session.execute(select(Ranking))).scalars().all()
    assert len(rows) == 9
    assert any(r.location_id == 32000002 for r in rows)


async def test_collect_rankings_marks_failed_when_nothing_succeeds(session, settings):
    await _seed_locations(session, 32000001, 32000002)

    async def always_fail(path, params):
        raise CocUpstreamError("上游 5xx")

    client = FakeClient(routes={"/rankings/": always_fail})
    status = await run_job("rankings", settings, session, client=client)

    assert status == "failed"
    run = (
        await session.execute(select(CollectorRun).order_by(CollectorRun.id.desc()))
    ).scalars().first()
    assert run.finished_at is not None
    assert run.error


async def test_collect_rankings_marks_success_when_all_ok(session, settings):
    await _seed_locations(session, 32000001, 32000002)
    client = FakeClient(
        routes={"/rankings/clans": {"items": [{"tag": "#AAA", "name": "A", "rank": 1}]}}
    )
    status = await run_job("rankings", settings, session, client=client)
    assert status == "success"

    run = (
        await session.execute(select(CollectorRun).order_by(CollectorRun.id.desc()))
    ).scalars().first()
    assert run.status == "success"
    assert run.error is None
    assert run.finished_at is not None


async def test_collect_rankings_skips_non_country_locations(session, settings):
    """只刷国家地区 —— 逐级地区有几百个，会让请求量翻十几倍。"""
    session.add(Location(id=32000001, name="CN", is_country=True))
    session.add(Location(id=32000002, name="Province", is_country=False))
    await session.commit()

    client = FakeClient(routes={"/rankings/clans": {"items": []}})
    await run_job("rankings", settings, session, client=client)

    clan_calls = [c for c in client.calls if c[1].endswith("/rankings/clans")]
    assert len(clan_calls) == 1
    assert clan_calls[0][1].startswith("/locations/32000001/")


async def test_collect_rankings_writes_all_five_kinds(session, settings):
    """五类地区榜都要刷。

    每类都必须给数据：``replace_rankings`` 对空列表是**清空该 scope**，只给两类
    数据的话另外三类刷完就是空 —— 那是正确行为，但断言要按这个前提写。
    """
    await _seed_locations(session, 32000001)
    client = FakeClient(
        routes={
            "/rankings/clans": {"items": [{"tag": "#AAA", "name": "A", "rank": 1}]},
            "/rankings/players": {"items": [{"tag": "#P1", "name": "P1", "rank": 1}]},
            "/rankings/capitals": {"items": [{"name": "首都", "rank": 1}]},
            "/rankings/clans-builder-base": {
                "items": [{"tag": "#AAA", "name": "A", "rank": 1}]
            },
            "/rankings/players-builder-base": {
                "items": [{"tag": "#P1", "name": "P1", "rank": 1}]
            },
        }
    )
    await run_job("rankings", settings, session, client=client)

    kinds = {
        r.kind for r in (await session.execute(select(Ranking))).scalars().all()
    }
    assert {str(k) for k in kinds} == {
        str(RankingKind.clans),
        str(RankingKind.players),
        str(RankingKind.capitals),
        str(RankingKind.clans_builder_base),
        str(RankingKind.players_builder_base),
    }


async def test_collect_rankings_passes_limit_to_official(session, settings):
    """limit 必须透传，否则官方默认只回一小页，榜单看着"少了一半"。"""
    await _seed_locations(session, 32000001)
    client = FakeClient(routes={"/rankings/clans": {"items": []}})
    await run_job("rankings", settings, session, client=client)

    for _, path, params in client.calls:
        assert params.get("limit") == 200, f"{path} 没有透传 limit: {params}"


# --------------------------------------------------------------------------- #
# 运行记录的形状
# --------------------------------------------------------------------------- #


async def test_run_job_records_a_running_row_before_work(session, settings):
    """干活时库里必须已经有一条 ``running`` 记录。

    进程被 kill 时那条记录会永远停在 running —— 这是"卡住了"的唯一信号。
    """
    seen: list[str] = []

    async def probe(path, params):
        run = (
            await session.execute(select(CollectorRun).order_by(CollectorRun.id.desc()))
        ).scalars().first()
        seen.append(run.status if run else "<none>")
        return {"items": []}

    client = FakeClient(routes={"/locations": probe})
    await run_job("static_data", settings, session, client=client)

    assert seen == ["running"]


async def test_run_job_records_failure_when_the_job_raises(session, settings):
    """job 内部抛异常必须留痕，不能让调度器崩掉。

    崩掉的话不是"这次失败"，而是"以后每一次都不再跑" —— 而且没人收到通知。
    """
    async def boom(path, params):
        raise RuntimeError("采集逻辑炸了")

    client = FakeClient(routes={"/locations": boom})
    status = await run_job("static_data", settings, session, client=client)

    assert status == "failed"
    run = (
        await session.execute(select(CollectorRun).order_by(CollectorRun.id.desc()))
    ).scalars().first()
    assert run.error["type"] == "RuntimeError"
    assert "采集逻辑炸了" in run.error["detail"]


async def test_run_job_rejects_unknown_job_name(session, settings):
    """拼错 job 名要响亮失败，不能静默跳过 —— 否则这个采集永远不发生。"""
    with pytest.raises(KeyError, match="rankngs"):
        await run_job("rankngs", settings, session, client=FakeClient())


async def test_run_job_is_registered_in_the_job_table(session, settings):
    assert set(service.JOBS) == {"static_data", "rankings", "leagues", "seasons"}


def test_every_job_in_the_table_is_actually_scheduled(settings):
    """JOBS 与 SCHEDULE_SPEC 必须一一对应 —— 只写进其中一处等于这个 job 永不运行。"""
    from app.collector.scheduler import SCHEDULE_SPEC

    scheduled = {name for _, name, _ in SCHEDULE_SPEC}
    assert scheduled == set(service.JOBS)