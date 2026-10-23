"""War Report 赛季快照日期的探测。

上游**没有**赛季列表接口（响应里也不带日期，无法从 ``latest`` 反推），所以「某个
赛季是否存在」只能拿 3.8 KB 的 ``players/countries?season=YYYY-MM-DD`` 去试：
200 即存在，404 ``snapshot not found`` 即不存在。完整榜是 231 KB，别拿它探测 ——
这是共享公共服务，探测贵在次数而不是数据量。

快照固定每 28 天一份、没有容差（``2026-10-06`` 与 ``2026-10-04`` 都是 404），
``±1`` 只是吸收发布时刻的漂移。

不取系统时间：``today`` 由调用方注入，测试才能确定（与 mapper 的 ``now`` 同规矩）。
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence

from app.warreport.client import WarReportClient, WarReportSnapshotNotFound

#: 页面只展示最近 3 个赛季，多拉无用。
SEASON_COUNT = 3
#: 上游固定每 28 天出一份快照。
SEASON_INTERVAL_DAYS = 28
#: 允许提前/延后 1 天。
PROBE_TOLERANCE_DAYS = 1
#: 首次部署（或节奏漂移回退）时逐日回溯的上限：一个周期 + 一周余量。
FIRST_RUN_LOOKBACK_DAYS = 35
#: 最新已知日期过了这么多天还探不到新快照，就当锚点不可信，回退逐日回溯。
FALLBACK_AFTER_DAYS = 31

#: 探测端点：只带一个赛季的国家榜，3.8 KB。
_PROBE_PATH = "/locations/global/rankings/players/countries"


async def snapshot_exists(client: WarReportClient, day: dt.date) -> bool:
    """该日期是否有快照。只吞「快照不存在」，其余错误照常冒泡。"""
    try:
        await client.get_json(_PROBE_PATH, {"season": day.isoformat()})
    except WarReportSnapshotNotFound:
        return False
    return True


async def discover_snapshots(
    client: WarReportClient, known: Sequence[str], today: dt.date
) -> list[str]:
    """探测出最近 ``SEASON_COUNT`` 个快照日期，倒序返回。

    ``known`` 是库里已有的赛季日期（``rankings.season_id``），用作正常路径的锚点：
    探 ``最新已知 + 28 天`` 那一档即可，最多 3 次请求。
    """
    known_days = [dt.date.fromisoformat(value) for value in known]
    if known_days:
        latest = max(known_days)
        candidate = latest + dt.timedelta(days=SEASON_INTERVAL_DAYS)
        found = await _probe_tier(client, candidate)
        if found is not None:
            return _finalize([*known_days, found])
        if (today - latest).days < FALLBACK_AFTER_DAYS:
            # 周期还没走完，只是本月的新快照尚未发布，明天再探。
            return _finalize(known_days)
        # 否则落到下面的逐日回溯：锚点已经不可信（上游改了节奏或删了旧赛季）。
    return await _backfill(client, today)


async def _backfill(client: WarReportClient, today: dt.date) -> list[str]:
    """从 ``today`` 往前逐日找最新一份，再按 28 天间隔往前补探。

    补探这一步不能省：只返回最新一份会让新部署的赛季榜只有 1 个选项，要等约 8 周
    才长到 3 个 —— 而需求就是「最近 3 个赛季」。

    只返回补探结果，**不与 ``known`` 合并**：走到这里说明锚点不可信，旧的 ``known``
    可能上游早已删除，继续拉它们只会白报失败。
    """
    anchor = None
    for offset in range(FIRST_RUN_LOOKBACK_DAYS):
        day = today - dt.timedelta(days=offset)
        if await snapshot_exists(client, day):
            anchor = day
            break
    if anchor is None:
        return []

    found = [anchor]
    while len(found) < SEASON_COUNT:
        candidate = found[-1] - dt.timedelta(days=SEASON_INTERVAL_DAYS)
        older = await _probe_tier(client, candidate)
        if older is None:
            break
        found.append(older)
    return _finalize(found)


async def _probe_tier(client: WarReportClient, candidate: dt.date) -> dt.date | None:
    """探一档：``candidate``、``candidate-1``、``candidate+1``，返回第一个存在的。

    三枪按这个顺序打（不是先往前），因为按 28 天节奏算出来的候选本身最可能命中。
    """
    for delta in (0, -PROBE_TOLERANCE_DAYS, PROBE_TOLERANCE_DAYS):
        day = candidate + dt.timedelta(days=delta)
        if await snapshot_exists(client, day):
            return day
    return None


def _finalize(days: Iterable[dt.date]) -> list[str]:
    """去重、倒序、只留最近 ``SEASON_COUNT`` 个，并转回 ISO 字符串。"""
    unique = sorted(set(days), reverse=True)
    return [day.isoformat() for day in unique[:SEASON_COUNT]]
