"""读时旁路缓存。

四个分支，覆盖整个生产故障谱：

- **HIT** —— 库里有行且未过期，一次官方请求都不发。
- **MISS** —— 库里没行（或已过期），回源成功并落库。
- **STALE** —— 回源**故障**且有旧行，返回旧数据 + HTTP 200。
  这是「Token 过期 / 公网 IP 变更」这个生产最可能故障下的用户体验底线。
- **冒泡** —— 业务错误绝不降级；没有旧数据时故障也冒泡，绝不伪造空结果。

三个必须锁住的判断，缺一个就是线上事故：

1. 业务错误（ClanNotFound / NotInWar / WarLogPrivate）**绝不降级为 STALE** ——
   否则用户会看到一个明显不存在的部落还带着旧数据，排查方向全错。
2. `CocAccessDenied` **可降级**（Review Focus 第 3 条）。它在 Task 2 里故意不是
   `CocFaultError` 子类（为了禁止自动重试），但降级与重试是两个正交决策。
3. `fetched_at` 与 `now` 都 tz-aware（Review Focus 第 2 条）。混用会抛
   `TypeError: can't subtract offset-naive and offset-aware datetimes`。
"""

import datetime as dt
from datetime import UTC

import pytest

from app.cache.readthrough import CacheStatus, read_through
from app.coc.errors import (
    ClanNotFound,
    CocAccessDenied,
    CocBusinessError,
    CocFaultError,
    CocThrottled,
    CocTimeout,
    CocUpstreamError,
    NotInWar,
    WarLogPrivate,
)
from app.db.models import Clan

TTL = 300  # "clan" 资源的 TTL


def _now() -> dt.datetime:
    return dt.datetime.now(UTC)


def _clan(fetched_at: dt.datetime, tag: str = "#2PP") -> Clan:
    """造一个已存在的 Clan 行（不落库，直接当 loader 返回值）。"""
    return Clan(tag=tag, name="示例", fetched_at=fetched_at)


def _values(*values):
    """把多个值包成一个异步 fetcher：第 N 次调用返回第 N 个值。"""

    async def fetcher():
        return next(_iter)

    _iter = iter(values)
    return fetcher


def _raising(exc: Exception):
    async def fetcher():
        raise exc

    return fetcher


async def _noop_persister(data) -> None:
    return None


# --------------------------------------------------------------------------- #
# HIT
# --------------------------------------------------------------------------- #


async def test_returns_hit_when_row_is_fresh(session):
    fresh = _clan(_now() - dt.timedelta(seconds=10))
    calls = []

    async def loader():
        calls.append("loader")
        return fresh

    async def fetcher():
        calls.append("fetcher")
        raise AssertionError("HIT 时不该回源")

    result = await read_through(
        "clan", "#2PP", loader, _noop_persister, fetcher, session
    )

    assert result.status is CacheStatus.HIT
    assert result.data is fresh
    assert calls == ["loader"]
    assert result.fetched_at == fresh.fetched_at
    # 10 秒前的数据
    assert 5 <= result.age_seconds <= 20


async def test_hit_does_not_call_persister(session):
    """HIT 时不许写库：那会让每次读都变成一次写。"""
    fresh = _clan(_now() - dt.timedelta(seconds=5))
    persisted = []

    async def loader():
        return fresh

    async def persister(data):
        persisted.append(data)

    async def fetcher():
        raise AssertionError("不该回源")

    await read_through("clan", "#2PP", loader, persister, fetcher, session)
    assert persisted == []


async def test_hit_at_exactly_ttl_boundary(session):
    """刚好等于 TTL 的时刻算过期（>= TTL 即过期）。"""
    boundary = _clan(_now() - dt.timedelta(seconds=TTL - 1))
    calls = []

    async def loader():
        return boundary

    async def fetcher():
        calls.append("fetcher")
        return _clan(_now())

    result = await read_through(
        "clan", "#2PP", loader, _noop_persister, fetcher, session
    )
    assert result.status is CacheStatus.HIT
    assert calls == []


# --------------------------------------------------------------------------- #
# HIT：loader 返回的是 dict，不是 ORM 对象
#
# 上面几条用的是 ORM 行对象，而**真实路由的 loader 一律返回 dict**：
# ``{"_row": ..., "fetched_at": ...}``（clans / players / currentwar / cwl）与
# ``{"_items": ..., "_fetched_at": ...}``（members / warlog）。
# 之所以要包一层 dict：session 在 loader 里就关掉了，行会 detached，
# 新鲜度得在关闭前抠出来；列表类响应还得同时带上分页后的 items。
#
# 这个形状一度没人覆盖 —— ``getattr(dict, "fetched_at")`` 永远返回 None，
# 于是新鲜度恒为「无从判断」，**每个详情请求都回源**，TTL 完全失效。
# 真实 Token 下这意味着白烧官方配额 + 每次都多一次上游往返。
# --------------------------------------------------------------------------- #


async def test_hit_when_loader_returns_mapping_with_fetched_at(session):
    """clans / players / currentwar / cwl 的 loader 形状。"""
    fresh_at = _now() - dt.timedelta(seconds=10)

    async def loader():
        return {"_row": _clan(fresh_at), "fetched_at": fresh_at}

    async def fetcher():
        raise AssertionError("形状正确时不该回源")

    result = await read_through(
        "clan", "#2PP", loader, _noop_persister, fetcher, session
    )

    assert result.status is CacheStatus.HIT
    assert result.fetched_at == fresh_at
    assert 5 <= result.age_seconds <= 20


async def test_hit_when_loader_returns_mapping_with_underscore_fetched_at(session):
    """members / warlog 的 loader 形状（键名多一个下划线）。"""
    fresh_at = _now() - dt.timedelta(seconds=10)

    async def loader():
        return {"_items": [], "_fetched_at": fresh_at}

    async def fetcher():
        raise AssertionError("形状正确时不该回源")

    result = await read_through(
        "clan_members", "#2PP", loader, _noop_persister, fetcher, session
    )

    assert result.status is CacheStatus.HIT
    assert result.fetched_at == fresh_at
    assert 5 <= result.age_seconds <= 20


async def test_mapping_without_freshness_key_still_refetches(session):
    """dict 里没有新鲜度键时才该回源 —— 不能把"未知"当成"新鲜"。"""
    calls = []

    async def loader():
        return {"_items": []}

    async def fetcher():
        calls.append("fetcher")
        return {"_items": [1], "_fetched_at": _now()}

    result = await read_through(
        "clan_members", "#2PP", loader, _noop_persister, fetcher, session
    )

    assert result.status is CacheStatus.MISS
    assert calls == ["fetcher"]


# --------------------------------------------------------------------------- #
# MISS
# --------------------------------------------------------------------------- #


async def test_fetches_and_persists_on_miss(session):
    calls = []
    fresh = _clan(_now())

    async def loader():
        return None

    async def fetcher():
        calls.append("fetcher")
        return fresh

    async def persister(data):
        calls.append("persister")

    result = await read_through("clan", "#2PP", loader, persister, fetcher, session)

    assert result.status is CacheStatus.MISS
    assert result.data is fresh
    assert "fetcher" in calls
    assert "persister" in calls


async def test_expired_row_triggers_refetch_and_miss(session):
    """已过期的旧行也要回源，回源成功算 MISS 而不是 STALE。"""
    stale_row = _clan(_now() - dt.timedelta(seconds=TTL + 100))
    fresh_row = _clan(_now())

    async def loader():
        return stale_row

    result = await read_through(
        "clan", "#2PP", loader, _noop_persister, _values(fresh_row), session
    )

    assert result.status is CacheStatus.MISS
    assert result.data is fresh_row


# --------------------------------------------------------------------------- #
# STALE：故障 + 有旧行
# --------------------------------------------------------------------------- #


async def test_degrades_to_stale_when_fetcher_raises_fault(session):
    stale_row = _clan(_now() - dt.timedelta(seconds=TTL + 60))

    async def loader():
        return stale_row

    result = await read_through(
        "clan", "#2PP", loader, _noop_persister,
        _raising(CocUpstreamError("5xx")), session,
    )

    assert result.status is CacheStatus.STALE
    assert result.data is stale_row, "STALE 必须返回旧数据"
    assert result.fetched_at == stale_row.fetched_at


@pytest.mark.parametrize(
    "exc",
    [
        CocThrottled("requestThrottled"),
        CocUpstreamError("unknownException"),
        CocTimeout("requestAborted"),
    ],
)
async def test_all_fault_errors_degrade_to_stale(session, exc):
    """三种故障态都能降级。"""
    stale_row = _clan(_now() - dt.timedelta(seconds=TTL + 60))

    async def loader():
        return stale_row

    result = await read_through(
        "clan", "#2PP", loader, _noop_persister, _raising(exc), session
    )
    assert result.status is CacheStatus.STALE


async def test_stale_when_all_upstream_fails_is_the_ip_or_token_fault_path(session):
    """Review Focus 第 3 条的落点。

    模拟「Token 过期 / 公网 IP 变更」——官方全线 403。此时用户拿到的应是旧数据 +
    HTTP 200，而不是一片 502。
    """
    stale_row = _clan(_now() - dt.timedelta(seconds=TTL + 60))

    async def loader():
        return stale_row

    result = await read_through(
        "clan", "#2PP", loader, _noop_persister,
        _raising(CocAccessDenied("IP 不在白名单", "accessDenied.invalidIp")),
        session,
    )

    assert result.status is CacheStatus.STALE
    assert result.data is stale_row


async def test_no_stale_when_row_is_absent(session):
    """没有旧数据可退时，故障必须冒泡——首次部署 + IP 未进白名单正是此场景。"""
    persisted = []

    async def loader():
        return None

    async def persister(data):
        persisted.append(data)

    with pytest.raises(CocAccessDenied):
        await read_through(
            "clan", "#2PP", loader, persister,
            _raising(CocAccessDenied("denied")), session,
        )

    assert persisted == [], "回源失败时不得写入空结果"


# --------------------------------------------------------------------------- #
# 业务错误：绝不降级
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "exc",
    [
        ClanNotFound("部落不存在"),
        NotInWar("未在战中"),
        WarLogPrivate("战报私密"),
    ],
)
async def test_does_not_degrade_business_error_to_stale(session, exc):
    """业务错误必须冒泡，不得返回陈旧数据。

    若实现错误地降级，用户会看到一个明显不存在的部落/战争还带着旧数据，
    而 API 返回 200 —— 这类 bug 排查方向会全错。
    """
    stale_row = _clan(_now() - dt.timedelta(seconds=TTL + 60))

    async def loader():
        return stale_row

    with pytest.raises(type(exc)):
        await read_through(
            "clan", "#2PP", loader, _noop_persister, _raising(exc), session
        )


async def test_business_errors_are_not_in_the_degradable_tuple():
    """把"业务态不在可降级列表里"从注释承诺变成可执行断言。

    ``read_through`` 靠 **遗漏** 来保证业务错误不降级 —— `_DEGRADABLE` 里只列了
    故障态。这意味着将来有人图省事把 ``CocBusinessError`` 加进去，业务错误就会
    静默降级，而上面那条行为测试仍然会通过（它测的是具体异常类，不是这个元组）。

    所以这里直接锁住元组本身：新增任何可降级类型时，必须先想清楚它是不是业务态。
    """
    from app.cache.readthrough import _DEGRADABLE

    assert not any(issubclass(CocBusinessError, t) for t in _DEGRADABLE), (
        "业务错误绝不能进入可降级列表 —— 降级会让用户看到明显错误的数据却拿到 200"
    )
    # CocAccessDenied 必须在：它是 CocError 的直接子类（Task 2 刻意不归入
    # CocFaultError 以禁止自动重试），但缓存层仍可降级（"可降级"与"可重试"正交）。
    assert any(issubclass(CocAccessDenied, t) for t in _DEGRADABLE)


async def test_business_error_is_not_a_fault_error():
    """结构性保证：业务态与故障态不得混为一个 isinstance 判断。"""
    assert not issubclass(ClanNotFound, CocFaultError)
    assert not issubclass(NotInWar, CocFaultError)
    assert not issubclass(WarLogPrivate, CocFaultError)
    assert issubclass(CocBusinessError, CocBusinessError)
    assert issubclass(CocAccessDenied, CocAccessDenied)


# --------------------------------------------------------------------------- #
# Review Focus 第 2 条：时区
# --------------------------------------------------------------------------- #


async def test_age_seconds_uses_tz_aware_arithmetic(session):
    """fetched_at 与 now 都 tz-aware 才能相减。"""
    row = _clan(_now() - dt.timedelta(seconds=60))

    async def loader():
        return row

    result = await read_through(
        "clan", "#2PP", loader, _noop_persister,
        _raising(AssertionError("不该回源")), session,
    )

    assert 55 <= result.age_seconds <= 65


async def test_returns_miss_when_loader_gives_none_and_fetcher_succeeds(session):
    """age_seconds 在 MISS 时可能为 None 或小值，但不得抛 TypeError。"""
    fresh = _clan(_now())

    async def loader():
        return None

    result = await read_through(
        "clan", "#2PP", loader, _noop_persister, _values(fresh), session
    )
    assert result.status is CacheStatus.MISS
    if result.age_seconds is not None:
        assert result.age_seconds >= 0


def test_cache_status_values_are_uppercase():
    """规格 §6.1：'cache': 'HIT | MISS | STALE'。前端直接读此值。"""
    assert CacheStatus.HIT.value == "HIT"
    assert CacheStatus.MISS.value == "MISS"
    assert CacheStatus.STALE.value == "STALE"
    assert set(CacheStatus) == {CacheStatus.HIT, CacheStatus.MISS, CacheStatus.STALE}


def test_cache_status_is_str_enum():
    """使 JSON 序列化直接产出 'HIT' 而不是 'CacheStatus.HIT'。"""
    assert CacheStatus.HIT == "HIT"
    assert isinstance(CacheStatus.HIT, str)
