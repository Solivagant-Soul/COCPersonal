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
        #: 探测阶段实际问过的赛季日期（按顺序）。用来验证锚点没被别的 scope 带偏。
        self.probed: list[str] = []

    async def get_json(self, path, params=None):
        if path.endswith("/players/countries"):
            season = params["season"]
            self.probed.append(season)
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


async def test_foreign_scope_seasons_are_not_used_as_the_probe_anchor(session):
    """别的 scope 写进同一个 kind 的 ``season_id`` 不是「我们采过的快照」。

    不钉 ``location_id`` 时，这种行会混进 ``known``：``max()`` 直接变成那个假日期，
    探测从它开始算，最后还会被当成真快照去拉榜 —— 库里凭空长出一季不存在的榜单。
    """
    session.add(Ranking(
        kind=str(RankingKind.wr_season_players), location_id=1,
        season_id="2026-12-01", rank=1, tag="#X", name="X",
        trophies=1, exp_level=1, fetched_at=NOW,
    ))
    await session.commit()

    fake = FakeWarReport({TODAY})
    result = await collect_warreport(fake, session, now=NOW)

    assert result["items_failed"] == 0
    assert "2026-12-01" not in fake.probed
    ghost = (await session.execute(
        select(func.count()).select_from(Ranking).where(
            Ranking.location_id == 32000000, Ranking.season_id == "2026-12-01"
        )
    )).scalar_one()
    assert ghost == 0


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


async def test_empty_armies_response_clears_the_table(session):
    """上游给 ``[]`` = 「确实没有配兵」→ 清空整表。

    与「非空但一行都映射不了」是两件事：那种情况必须失败并保留旧数据
    （见下一条用例），否则上游字段改名会静默清空阵容页。
    """
    await collect_warreport(FakeWarReport({TODAY}), session, now=NOW)
    assert (await session.execute(
        select(func.count()).select_from(WarReportArmy)
    )).scalar_one() == 1

    class NoArmies(FakeWarReport):
        async def get_json(self, path, params=None):
            if path == "/armies":
                return []
            return await super().get_json(path, params)

    result = await collect_warreport(NoArmies({TODAY}), session, now=NOW)

    assert result["items_failed"] == 0
    assert (await session.execute(
        select(func.count()).select_from(WarReportArmy)
    )).scalar_one() == 0


async def test_unmappable_armies_response_fails_and_keeps_old_rows(session):
    """非空响应里没有一行能映射 → 失败，**旧数据必须留着**。

    上游改名（例如 ``percentage`` → ``useRate``）时每一行都会缺必填列。
    若照常整表替换，就是 DELETE 全表 + INSERT 0 行：阵容页静默清空，
    采集结果还是 success —— 故障没有任何报错可看。
    """
    await collect_warreport(FakeWarReport({TODAY}), session, now=NOW)

    class RenamedFields(FakeWarReport):
        async def get_json(self, path, params=None):
            if path == "/armies":
                # 名字还在，但必填列全没了（模拟上游字段改名）
                return [{"name": "Thrower", "useRate": 27.27}, {"name": "Yeti"}]
            return await super().get_json(path, params)

    result = await collect_warreport(RenamedFields({TODAY}), session, now=NOW)

    assert result["items_failed"] == 1
    assert "2 条" in str(result["detail"])
    rows = (await session.execute(select(WarReportArmy))).scalars().all()
    assert [row.canonical_key for row in rows] == ["k1"]


async def test_unmappable_season_board_fails_and_keeps_old_rows(session):
    """非空的赛季榜响应里没有一行能映射 → 该 scope 失败，旧数据保留。

    这是配兵那条守卫的姊妹坑：上游把 ``tag`` 改名后 mapper 会丢掉每一行，
    照常替换就是「DELETE 该 scope + INSERT 0 行」—— 榜空了、采集记 success，
    连这一季都会从 ``/rankings/warreport/seasons`` 里消失（那个列表按这些行聚合）。
    """
    await collect_warreport(FakeWarReport({TODAY}), session, now=NOW)
    before = (await session.execute(
        select(func.count()).select_from(Ranking)
    )).scalar_one()
    assert before == 2  # players + clans

    class RenamedFields(FakeWarReport):
        async def get_json(self, path, params=None):
            if path.endswith("/rankings/players"):
                # 名次还在，但 tag 没了 → player_item 返回 None
                return [{"name": "P1", "rank": 1}, {"name": "P2", "rank": 2}]
            return await super().get_json(path, params)

    result = await collect_warreport(RenamedFields({TODAY}), session, now=NOW)

    # players 那个 scope 失败，clans 与配兵照常成功
    assert result["items_failed"] == 1
    assert "2 条" in str(result["detail"])
    rows = (await session.execute(
        select(Ranking).where(Ranking.kind == str(RankingKind.wr_season_players))
    )).scalars().all()
    assert [row.tag for row in rows] == ["#P1"]


async def test_stale_anchor_with_no_snapshot_is_logged(session):
    """库里有赛季却一个也探不到时，必须留一行 WARNING。

    这种轮次仍然是 success（阵容照常刷），但赛季榜会**永远**停在旧数据 ——
    没有日志的话，只有用户发现页面不更新才会被注意到。

    用自己挂的 handler 而不是 ``caplog``：本仓库的 pytest-asyncio 装配下，
    ``caplog`` **抓不到在 await 里打出的日志**（实测 caplog.text 恒为空，
    同样的 logger 在同步用例里却能抓到），用它只会写出一条永远失败的假测试。
    """
    import logging

    class ListHandler(logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self.records: list[logging.LogRecord] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.records.append(record)

    class StaleAnchor(FakeWarReport):
        async def get_json(self, path, params=None):
            if path.endswith("/players/countries"):
                self.probed.append(params["season"])
                raise WarReportSnapshotNotFound("snapshot not found")
            return await super().get_json(path, params)

    # 先把库里灌成一个"很久以前的快照"（超过 FALLBACK_AFTER_DAYS），
    # 让 discover_snapshots 走逐日回溯分支，而回溯窗口里一个都探不到。
    old = (NOW.date() - dt.timedelta(days=60)).isoformat()
    session.add(Ranking(
        kind=str(RankingKind.wr_season_players), location_id=32000000,
        season_id=old, rank=1, tag="#OLD", name="OLD",
        trophies=1, exp_level=1, fetched_at=NOW,
    ))
    await session.commit()

    handler = ListHandler()
    job_logger = logging.getLogger("coc.collector.warreport")
    previous_level = job_logger.level
    # **必须显式打开**：conftest 的 session fixture 会用 alembic `command.upgrade()`，
    # 而 alembic 读 alembic.ini 时走 `logging.config.fileConfig(...)`，其默认
    # `disable_existing_loggers=True` 会把**已经存在**的 logger 全部 disable 掉
    # （包括本模块的 logger）。不恢复的话，这里一条记录都收不到，测试永远绿不了。
    previous_disabled = job_logger.disabled
    job_logger.disabled = False
    job_logger.addHandler(handler)
    job_logger.setLevel(logging.WARNING)
    try:
        result = await collect_warreport(StaleAnchor(set()), session, now=NOW)
    finally:
        job_logger.removeHandler(handler)
        job_logger.setLevel(previous_level)
        job_logger.disabled = previous_disabled

    assert result["items_failed"] == 0
    assert any("没探到任何快照" in record.getMessage() for record in handler.records), [
        record.getMessage() for record in handler.records
    ]


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
