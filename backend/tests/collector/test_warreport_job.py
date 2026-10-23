"""War Report 每日采集 job。

要守住四条线：

1. **赛季榜按快照日期分 scope 全量替换**（players / clans 各一个 scope）。
2. **配兵与赛季发现解耦**：``discover_snapshots()`` 返回空列表时**仍要**刷
   ``GET /armies`` —— ``[]`` 只表示"没探到快照"，绝不表示"该清空阵容"。
3. **部分失败必须如实记账**：一个 scope 挂了，其它 scope 的数据要留下来，
   ``run_job`` 把整轮判成 ``partial``。
4. **配兵的 position 在过滤与去重之后仍从 1 连续**：``army_row`` 会丢掉缺
   not-null 字段的行，先编号后过滤会留下 1、3、4 这样的空洞。

替身按 HTTP 路径分发，不按 endpoint 函数名（与 ``test_jobs.py`` 同一约定）。
"""

import datetime as dt
from datetime import UTC

import pytest
from sqlalchemy import func, select

from app.collector.jobs.warreport import collect_warreport
from app.collector.rankings_service import RankingKind
from app.collector.service import run_job
from app.db.models import CollectorRun, Ranking, WarReportArmy
from app.warreport.client import WarReportError, WarReportSnapshotNotFound

NOW = dt.datetime.now(UTC)
TODAY = NOW.date().isoformat()


class FakeWarReport:
    def __init__(self, snapshots, fail=()):
        self.snapshots = set(snapshots)
        self.fail = set(fail)

    async def get_json(self, path, params=None):
        if path.endswith("/players/countries"):
            season = params["season"]
            if season not in self.snapshots:
                raise WarReportSnapshotNotFound("snapshot not found")
            return []
        if path in self.fail:
            raise WarReportError("boom", status_code=503)
        if path.endswith("/rankings/players"):
            return [{"tag": "#p1", "name": "P1", "rank": 1, "expLevel": 300,
                     "trophies": 6000, "attackWins": 3, "defenseWins": 2,
                     "clan": {"tag": "#c1", "name": "C1", "clanLevel": 18}}]
        if path.endswith("/rankings/clans"):
            return [{"tag": "#c1", "name": "C1", "rank": 1, "clanLevel": 18,
                     "members": 45, "clanPoints": 5000}]
        if path == "/armies":
            return [{"name": "Thrower", "canonicalKey": "k1",
                     "armyShareCode": "sc", "armyLink": "https://link",
                     "playerCount": 54, "useCount": 332, "percentage": 27.27,
                     "averageStars": 2.73, "averageDestruction": 97.25}]
        raise AssertionError(f"unexpected path {path}")

    async def aclose(self):  # run_job 自建客户端时会调；注入的替身也要有
        pass


@pytest.fixture
def settings():
    from app.config import Settings

    return Settings(
        coc_api_token="t",
        database_url="postgresql+asyncpg://x@localhost/x",
        app_role="collector",
    )


async def test_collect_writes_rankings_and_armies(session):
    result = await collect_warreport(FakeWarReport({TODAY}), session, now=NOW)
    assert result["items_ok"] == 3
    assert result["items_failed"] == 0

    players = (await session.execute(
        select(Ranking).where(Ranking.kind == str(RankingKind.wr_season_players))
    )).scalars().all()
    assert len(players) == 1
    assert players[0].season_id == TODAY
    assert players[0].location_id == 32000000
    assert players[0].clan_tag == "#C1"

    clans = (await session.execute(
        select(Ranking).where(Ranking.kind == str(RankingKind.wr_season_clans))
    )).scalars().all()
    assert clans[0].points == 5000

    armies = (await session.execute(select(WarReportArmy))).scalars().all()
    assert len(armies) == 1
    assert armies[0].position == 1


async def test_second_run_replaces_instead_of_duplicating(session):
    fake = FakeWarReport({TODAY})
    await collect_warreport(fake, session, now=NOW)
    second = await collect_warreport(fake, session, now=NOW)
    # 第二次也必须**真的重采**：只把行数没翻倍当成通过，一个"已知道的快照就跳过"
    # 的实现同样能骗过它 —— 而那样榜单会永远停在第一次的数据。
    assert second["items_ok"] == 3
    assert second["items_failed"] == 0
    total = (await session.execute(
        select(func.count()).select_from(Ranking)
    )).scalar_one()
    assert total == 2
    assert (await session.execute(
        select(func.count()).select_from(WarReportArmy)
    )).scalar_one() == 1


async def test_partial_failure_keeps_other_scopes(session):
    status = await run_job(
        "warreport", session=session,
        client=FakeWarReport({TODAY}, fail={"/locations/global/rankings/clans"}),
    )
    assert status == "partial"
    assert (await session.execute(
        select(func.count()).select_from(Ranking)
    )).scalar_one() == 1
    # 一个 scope 失败不能拦住后面的配兵刷新 —— 这就是"containment"本身
    assert (await session.execute(
        select(func.count()).select_from(WarReportArmy)
    )).scalar_one() == 1
    run = (await session.execute(select(CollectorRun))).scalars().one()
    assert run.status == "partial"


async def test_commit_failure_only_fails_that_scope(session, monkeypatch):
    """``commit()`` 本身失败也只算那一个 scope 失败。

    commit 在 per-scope ``try`` 之外时，一次提交失败会冒泡出 ``collect_warreport``：
    剩下的 scope 与配兵全都不采，``run_job`` 还把整轮记成 failed —— 尽管前面的
    scope 早已提交。这里让第二次 commit（clans scope）抛一次，验证边界收紧到位。
    """
    real_commit = session.commit
    calls = {"n": 0}

    async def flaky_commit():
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("commit 掉线")
        await real_commit()

    monkeypatch.setattr(session, "commit", flaky_commit)

    result = await collect_warreport(FakeWarReport({TODAY}), session, now=NOW)

    assert result["items_ok"] == 2  # players + armies；失败的那个不计 ok
    assert result["items_failed"] == 1
    assert "commit 掉线" in str(result["detail"])
    # 第一个 scope（players）已经提交 → 留得住；失败的那个被回滚掉
    kinds = (await session.execute(select(Ranking.kind))).scalars().all()
    assert kinds == [str(RankingKind.wr_season_players)]
    # 配兵照常刷新
    assert (await session.execute(
        select(func.count()).select_from(WarReportArmy)
    )).scalar_one() == 1


async def test_discovery_failure_is_recorded_as_failed(session):
    class Broken(FakeWarReport):
        async def get_json(self, path, params=None):
            raise WarReportError("network down")

    status = await run_job("warreport", session=session, client=Broken(set()))
    assert status == "failed"


async def test_armies_are_still_refreshed_when_no_snapshot_is_discovered(session):
    """``[]`` 只表示"没探到快照"，不是"清空阵容"。

    上游在一整个回溯窗口内都没有快照时（新部署、上游删档），阵容仍必须照常刷新 ——
    否则阵容页会跟着赛季榜一起静默停更。
    """
    result = await collect_warreport(FakeWarReport(set()), session, now=NOW)

    assert result["items_failed"] == 0
    # 没有快照 → 只有 armies 这一个成功 scope
    assert result["items_ok"] == 1
    assert (await session.execute(
        select(func.count()).select_from(Ranking)
    )).scalar_one() == 0
    assert (await session.execute(
        select(func.count()).select_from(WarReportArmy)
    )).scalar_one() == 1


async def test_army_positions_stay_contiguous_after_filtering_and_dedup(session):
    """脏行与重复 key 都不能在 position 上留空洞，也不能让整次替换失败。"""

    class MessyArmies(FakeWarReport):
        async def get_json(self, path, params=None):
            if path == "/armies":
                base = {
                    "canonicalKey": "k1",
                    "armyShareCode": "sc",
                    "armyLink": "https://link",
                    "playerCount": 54,
                    "useCount": 332,
                    "percentage": 27.27,
                    "averageStars": 2.73,
                    "averageDestruction": 97.25,
                }
                return [
                    {**base, "name": "A"},
                    # 缺 armyShareCode → army_row 返回 None，必须被丢掉
                    {**base, "canonicalKey": "dirty", "name": "Dirty",
                     "armyShareCode": None},
                    {**base, "canonicalKey": "k2", "name": "B"},
                    # 重复 key（保留先出现的那条）→ 唯一约束不会被撞
                    {**base, "name": "A again"},
                ]
            return await super().get_json(path, params)

    await collect_warreport(MessyArmies({TODAY}), session, now=NOW)

    rows = (await session.execute(
        select(WarReportArmy).order_by(WarReportArmy.position)
    )).scalars().all()
    assert [(row.position, row.canonical_key) for row in rows] == [
        (1, "k1"),
        (2, "k2"),
    ]


async def test_run_job_builds_the_warreport_client_for_the_warreport_job(
    monkeypatch, settings, session
):
    """自建客户端时必须按 job 名选 War Report 客户端，而不是照旧造 CocClient。

    其它用例都显式注入 client，这条是唯一能看见"选择"本身的地方 —— 选错的话
    线上第一次定时采集就会拿 Supercell 的客户端去打 warreport.app。
    """
    fake = FakeWarReport({TODAY})
    seen_settings = []

    def fake_client_from_settings(effective):
        seen_settings.append(effective)
        return fake

    monkeypatch.setattr(
        "app.warreport.client.client_from_settings", fake_client_from_settings
    )

    status = await run_job("warreport", settings, session)

    assert status == "success"
    assert seen_settings == [settings]
    assert (await session.execute(
        select(func.count()).select_from(WarReportArmy)
    )).scalar_one() == 1
