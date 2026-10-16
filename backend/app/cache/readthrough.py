"""读时旁路缓存。

流程：先查库 → 新鲜则 HIT；否则回源 → 成功则落库并 MISS；回源**故障**且有旧行
则 STALE（返回旧数据，仍 HTTP 200）；业务错误与"无旧数据可退"一律冒泡。

三个判断写死了，不要改：

1. **业务错误绝不降级**（`ClanNotFound` / `NotInWar` / `WarLogPrivate`）。
   降级会让用户看到一个明显不存在的部落还带着旧数据、API 返回 200 ——
   这类 bug 的排查方向会全错。
2. **`CocAccessDenied` 可降级**（Review Focus 第 3 条）。它代表 Token 过期或
   IP 白名单失效（直连时是服务器 IP，走代理 R26 时是代理 IP），会让官方调用
   **全线**失败；一律重抛的话用户面对的是一片 502。
   降级让已有缓存继续服务，而告警是正交的观测关注点，由
   `app/api/errors.py` 负责，**不靠禁止降级来实现**。
   注意它在 Task 2 里故意不是 `CocFaultError` 子类（为了禁止自动重试），
   所以这里必须与故障态显式并列。
3. **时间一律 tz-aware**（Review Focus 第 2 条）。`fetched_at` 与 `now` 混用
   naive / aware 会抛 `TypeError: can't subtract offset-naive and
   offset-aware datetimes`，而且在大陆服务器上会让 TTL 判定偏差 8 小时。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from datetime import UTC
from enum import Enum
from typing import Awaitable, Callable, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.ttl import get_ttl
from app.coc.errors import CocAccessDenied, CocError, CocFaultError

T = TypeVar("T")

# 可降级为 STALE 的异常类型。业务态刻意不在内。
_DEGRADABLE: tuple[type[CocError], ...] = (CocFaultError, CocAccessDenied)


class CacheStatus(str, Enum):
    """缓存状态。

    值必须是大写 —— 规格 §6.1 的 ``"cache": "HIT | MISS | STALE"`` 与 §3 数据流
    的 ``meta.cache=HIT`` 逐字一致，前端直接读此值，改大小写即破坏契约。
    """

    HIT = "HIT"
    MISS = "MISS"
    STALE = "STALE"


@dataclass
class ReadThroughResult[T]:
    data: T
    status: CacheStatus
    fetched_at: dt.datetime | None = None
    age_seconds: int | None = None


async def read_through[T](
    resource: str,
    key: str,
    loader: Callable[[], Awaitable[T]],
    persister: Callable[[T], Awaitable[None]],
    fetcher: Callable[[], Awaitable[T]],
    session: AsyncSession,
) -> ReadThroughResult[T]:
    """读时旁路。

    参数全部由调用方提供，本函数不自己查库、不自己请求 —— 这样它才能在不依赖
    FastAPI 与具体 ORM 模型的情况下被完整测试。

    - ``resource``：TTL 表的键
    - ``key``：用于日志与错误信息，不参与缓存判定
    - ``loader``：查库；命中返回行，未命中返回 None
    - ``persister``：回源成功后落库
    - ``fetcher``：回源；成功返回新数据，失败抛 CocError
    """
    ttl = get_ttl(resource)
    now = dt.datetime.now(UTC)

    existing = await loader()
    if existing is not None:
        row_fetched_at = _fetched_at_of(existing)
        # TTL 边界：>= ttl 即过期（刚好等于时算过期，不做四舍五入）
        if row_fetched_at is not None and row_fetched_at + dt.timedelta(
            seconds=ttl
        ) > now:
            return _hit(existing, row_fetched_at, now)

    try:
        data = await fetcher()
    except _DEGRADABLE as exc:
        # 故障且无旧行可退：冒泡，让上层返回 502（首次部署 + IP 未进白名单正是此场景）
        if existing is None:
            raise
        return _stale(existing, _fetched_at_of(existing), now, resource, key, exc)

    await persister(data)
    fetched_at = _fetched_at_of(data)
    return ReadThroughResult(
        data=data,
        status=CacheStatus.MISS,
        fetched_at=fetched_at,
        age_seconds=_age(fetched_at, now),
    )


# --------------------------------------------------------------------------- #
# 内部辅助
# --------------------------------------------------------------------------- #


def _fetched_at_of(value: object) -> dt.datetime | None:
    """取对象的 ``fetched_at``。缺失或为 None 时返回 None。

    用 getattr 而不是属性访问：loader 返回的可能是 ORM 实例、也可能是测试里的
    轻量替身。缺字段时当作"无从判断新鲜度"，走上回源而不是假装新鲜。
    """
    fetched_at = getattr(value, "fetched_at", None)
    return fetched_at if isinstance(fetched_at, dt.datetime) else None


def _age(fetched_at: dt.datetime | None, now: dt.datetime) -> int | None:
    if fetched_at is None:
        return None
    # 两个操作数都 tz-aware 才能相减；naive 混 aware 会抛 TypeError
    return int((now - fetched_at).total_seconds())


def _hit[T](
    existing: T, fetched_at: dt.datetime, now: dt.datetime
) -> ReadThroughResult[T]:
    return ReadThroughResult(
        data=existing,
        status=CacheStatus.HIT,
        fetched_at=fetched_at,
        age_seconds=_age(fetched_at, now),
    )


def _stale[T](
    existing: T,
    fetched_at: dt.datetime | None,
    now: dt.datetime,
    resource: str,
    key: str,
    exc: CocError,
) -> ReadThroughResult[T]:
    """构造 STALE 结果。

    告警不在这里做：缓存层的职责是让上层继续服务，log/alert 由
    `app/api/errors.py` 处理同一个异常链上的观测关注点。
    """
    return ReadThroughResult(
        data=existing,
        status=CacheStatus.STALE,
        fetched_at=fetched_at,
        age_seconds=_age(fetched_at, now),
    )
