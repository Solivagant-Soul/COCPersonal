"""榜单采集。

**串行执行**，不并发 —— 并发会让几十个请求同时撞上令牌桶（Task 2 的
``MemoryRateLimiter``），直接被官方限流。限速是 ``CocClient`` 的职责，这一层
不再自己写 ``sleep``（两处限速叠加会让采集慢到没必要）。

**只刷国家地区**（``is_country = true``）：逐级地区有几百个，刷全量会让请求量
翻十几倍，而小程序用户查的是国家级榜单。
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.coc import endpoints as coc
from app.coc.client import CocClient
from app.collector.rankings_service import RankingKind, replace_rankings
from app.db.models import Location

logger = logging.getLogger("coc.collector.rankings")

#: (kind, 拉取函数)。都城榜没有 tag，映射层会相应处理。
_KIND_FETCHERS = {
    RankingKind.clans: coc.get_clan_rankings,
    RankingKind.players: coc.get_player_rankings,
    RankingKind.capitals: coc.get_capital_rankings,
    RankingKind.clans_builder_base: coc.get_clan_rankings_builder_base,
    RankingKind.players_builder_base: coc.get_player_rankings_builder_base,
}


async def collect_rankings(
    client: CocClient, session: AsyncSession, now: dt.datetime | None = None
) -> dict[str, int]:
    """刷全部国家地区 × 5 类地区榜。

    返回 ``{"items_ok": n, "items_failed": m}`` —— **部分失败必须如实记账**。
    笼统记成成功会让"某个地区的榜单缺了一半"永远没人发现。
    """
    now = now or dt.datetime.now(dt.UTC)
    # **只取 id，不要拿 ORM 实例**：``rollback()`` 会让已加载的实例 expire，
    # 循环里再读 ``location.id`` 就是一次同步懒加载 —— 异步会话里直接
    # ``MissingGreenlet``，一个 scope 的数据库错误会把整轮采集带崩
    # （2026-10-21 线上：死锁 → 回滚 → 下一个 ``location.id`` → job failed）。
    location_ids = (
        await session.execute(select(Location.id).where(Location.is_country.is_(True)))
    ).scalars().all()

    ok = 0
    failed = 0
    failures: list[str] = []
    for location_id in location_ids:
        for kind, fetch in _KIND_FETCHERS.items():
            try:
                payload = await fetch(client, location_id, limit=200)
            except Exception as exc:  # noqa: BLE001 - 单个 scope 失败不能拖垮整轮
                failed += 1
                failures.append(f"{kind}/{location_id}: {exc}")
                logger.warning(
                    "rankings %s/%s 采集失败: %s", kind, location_id, exc
                )
                continue
            items = (payload or {}).get("items") or []
            try:
                written = await replace_rankings(
                    session, kind, location_id, None, None, items, now=now
                )
            except Exception as exc:  # noqa: BLE001
                failed += 1
                failures.append(f"{kind}/{location_id} 落库失败: {exc}")
                logger.warning("rankings %s/%s 落库失败: %s", kind, location_id, exc)
                # 这一条失败不能带着整个事务一起回滚 —— 前面成功的 scope 已经提交了
                await session.rollback()
                continue
            # **每个 scope 单独提交**：事务越短，和另一个采集进程撞车的窗口越小；
            # 半路失败也不会丢掉已经写好的 scope（顾问锁也随 commit 释放）。
            await session.commit()
            ok += 1
            logger.debug("rankings %s/%s 写入 %s 条", kind, location_id, written)

    # 把失败明细一并带回，run_job 会写进 collector_runs.error。
    # 不带的话线上只剩一个 items_failed=1，得翻日志才知道是哪个地区。
    if failures:
        return {"items_ok": ok, "items_failed": failed, "detail": failures[:50]}
    return {"items_ok": ok, "items_failed": failed}