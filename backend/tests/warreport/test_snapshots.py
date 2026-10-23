import datetime as dt

import pytest

from app.warreport.client import WarReportError, WarReportSnapshotNotFound
from app.warreport.snapshots import discover_snapshots, snapshot_exists


class FakeClient:
    def __init__(self, valid: set[str], error: bool = False):
        self.valid = valid
        self.error = error
        self.calls: list[str] = []

    async def get_json(self, path, params=None):
        if self.error:
            raise WarReportError("boom")
        day = params["season"]
        self.calls.append(day)
        if day not in self.valid:
            raise WarReportSnapshotNotFound("snapshot not found")
        return []


async def test_first_run_probes_backwards_and_stops_at_latest():
    today = dt.date(2026, 10, 23)
    client = FakeClient({"2026-10-05"})
    assert await discover_snapshots(client, [], today) == ["2026-10-05"]
    assert client.calls[0] == "2026-10-23"
    # 23 日到 5 日逐日 19 次；命中后再按 28 天间隔补探 09-07 那一档的 3 个候选，
    # 全不命中即停（不再往 08-10 探）
    assert len(client.calls) == 19 + 3


async def test_first_run_backfills_up_to_three_snapshots():
    """首次运行必须一次凑够 3 个赛季。

    只找到「最新一份」就停会让新部署的赛季榜只有 1 个选项，要等两个采集周期
    （约 8 周）才长到 3 个 —— 而需求就是「最近 3 个赛季」。
    """
    today = dt.date(2026, 10, 23)
    client = FakeClient({"2026-10-05", "2026-09-07", "2026-08-10"})
    assert await discover_snapshots(client, [], today) == [
        "2026-10-05",
        "2026-09-07",
        "2026-08-10",
    ]


async def test_known_dates_only_probe_three_candidates():
    today = dt.date(2026, 10, 23)
    client = FakeClient(set())  # 还没有新快照
    known = ["2026-10-05", "2026-09-07", "2026-08-10"]
    assert await discover_snapshots(client, known, today) == known
    assert client.calls == ["2026-11-02", "2026-11-01", "2026-11-03"]


async def test_new_snapshot_is_merged_and_trimmed_to_three():
    today = dt.date(2026, 11, 2)
    client = FakeClient({"2026-11-02"})
    known = ["2026-10-05", "2026-09-07", "2026-08-10"]
    assert await discover_snapshots(client, known, today) == [
        "2026-11-02", "2026-10-05", "2026-09-07",
    ]


async def test_stale_anchor_falls_back_to_backward_probe():
    today = dt.date(2026, 11, 20)
    client = FakeClient({"2026-11-16"})
    known = ["2026-10-05"]
    assert await discover_snapshots(client, known, today) == ["2026-11-16"]


async def test_snapshot_exists_returns_false_on_404():
    client = FakeClient({"2026-10-05"})
    assert await snapshot_exists(client, dt.date(2026, 10, 5)) is True
    assert await snapshot_exists(client, dt.date(2026, 10, 4)) is False


async def test_network_error_propagates():
    client = FakeClient(set(), error=True)
    with pytest.raises(WarReportError):
        await discover_snapshots(client, [], dt.date(2026, 10, 23))


async def test_probe_uses_the_small_countries_endpoint():
    """探测只打 3.8 KB 的 countries 端点；完整榜是 231 KB，蹭共享公共服务不划算。"""
    seen: list[tuple[str, dict[str, str]]] = []

    class RecordingClient:
        async def get_json(self, path, params=None):
            seen.append((path, params))
            return []

    assert await snapshot_exists(RecordingClient(), dt.date(2026, 10, 5)) is True
    assert seen == [
        ("/locations/global/rankings/players/countries", {"season": "2026-10-05"})
    ]
