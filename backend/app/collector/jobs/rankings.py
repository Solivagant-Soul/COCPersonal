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
    locations = (
        await session.execute(select(Location).where(Location.is_country.is_(True)))
    ).scalars().all()

    ok = 0
    failed = 0
    failures: list[str] = []
    for location in locations:
        for kind, fetch in _KIND_FETCHERS.items():
            try:
                payload = await fetch(client, location.id, limit=200)
            except Exception as exc:  # noqa: BLE001 - 单个 scope 失败不能拖垮整轮
                failed += 1
                failures.append(f"{kind}/{location.id}: {exc}")
                logger.warning(
                    "rankings %s/%s 采集失败: %s", kind, location.id, exc
                )
                continue
            items = (payload or {}).get("items") or []
            try:
                written = await replace_rankings(
                    session, kind, location.id, None, None, items, now=now
                )
            except Exception as exc:  # noqa: BLE001
                failed += 1
                failures.append(f"{kind}/{location.id} 落库失败: {exc}")
                logger.warning("rankings %s/%s 落库失败: %s", kind, location.id, exc)
                # 这一条失败不能带着整个事务一起回滚 —— 前面成功的 scope 已经写好了
                await session.rollback()
                continue
            ok += 1
            logger.debug("rankings %s/%s 写入 %s 条", kind, location.id, written)

    await session.commit()
    # 把失败明细一并带回，run_job 会写进 collector_runs.error。
    # 不带的话线上只剩一个 items_failed=1，得翻日志才知道是哪个地区。
    if failures:
        return {"items_ok": ok, "items_failed": failed, "detail": failures[:50]}
    return {"items_ok": ok, "items_failed": failed}