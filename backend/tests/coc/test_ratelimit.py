"""进程内令牌桶限速。

限速对象是对官方 Supercell API 的出站请求。两个关键性质：
1. 一窗口内允许多次 acquire 消耗已攒下的令牌，不因抢锁而串行化。
2. 令牌耗尽后确实要等到下一枚令牌，且等待期间**不持锁**。
"""

import asyncio
import time

import pytest

from app.coc.ratelimit import MemoryRateLimiter


async def test_allows_rate_requests_within_one_second():
    limiter = MemoryRateLimiter(rate=8)
    start = time.monotonic()
    for _ in range(8):
        await limiter.acquire()
    assert time.monotonic() - start < 0.5
    await limiter.close()


async def test_tenth_request_waits_for_the_next_token():
    """令牌耗尽后必须等下一枚，不能立即返回。"""
    limiter = MemoryRateLimiter(rate=4)
    for _ in range(4):
        await limiter.acquire()
    # rate=4 → 一枚令牌需 0.25s；timeout 取 0.05s，5 倍裕量，不依赖精确计时
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(limiter.acquire(), timeout=0.05)
    await limiter.close()


async def test_exhausted_acquire_eventually_succeeds():
    """被限速的调用最终应成功，而不是永久阻塞。"""
    limiter = MemoryRateLimiter(rate=4)
    for _ in range(4):
        await limiter.acquire()
    start = time.monotonic()
    await limiter.acquire()
    elapsed = time.monotonic() - start
    await limiter.close()
    assert 0.05 < elapsed


async def test_burst_defaults_to_rate():
    limiter = MemoryRateLimiter(rate=4)
    start = time.monotonic()
    for _ in range(4):
        await limiter.acquire()
    assert time.monotonic() - start < 0.5
    await limiter.close()


async def test_tokens_refill_over_time():
    """用完桶后等一会儿应能再次立刻拿到令牌。"""
    limiter = MemoryRateLimiter(rate=4)
    for _ in range(4):
        await limiter.acquire()
    await asyncio.sleep(0.4)
    start = time.monotonic()
    await limiter.acquire()
    assert time.monotonic() - start < 0.05
    await limiter.close()


async def test_close_is_not_blocked_while_a_caller_waits():
    """等待令牌不得持锁，否则需要同一把锁的 close() 会一起卡住。"""
    limiter = MemoryRateLimiter(rate=8, burst=1)
    await limiter.acquire()  # 桶空了
    waiter = asyncio.create_task(limiter.acquire())  # 要等约 0.125s
    await asyncio.sleep(0.02)

    start = time.monotonic()
    await limiter.close()
    blocked_for = time.monotonic() - start

    waiter.cancel()
    await asyncio.gather(waiter, return_exceptions=True)
    assert blocked_for < 0.05, f"close 被等待者挡住 {blocked_for:.3f}s"


async def test_acquire_after_close_raises():
    limiter = MemoryRateLimiter(rate=2)
    await limiter.close()
    with pytest.raises(RuntimeError):
        await limiter.acquire()


async def test_close_can_be_called_twice():
    limiter = MemoryRateLimiter(rate=2)
    await limiter.acquire()
    await limiter.close()
    await limiter.close()


def test_rate_must_be_positive():
    with pytest.raises(ValueError):
        MemoryRateLimiter(rate=0)
