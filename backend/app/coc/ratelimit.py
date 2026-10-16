"""进程内令牌桶限速。

用令牌桶而非固定窗口：官方建议约 10 req/s，我们把上限压到 8 req/s 留余量，
允许短时突发。限速对象是对官方 Supercell API 的出站请求，**不**用于对外
（小程序）请求——那是 IP 级限流，在 ``app/middleware.py``。

实现要点：令牌不足时**释放锁再睡眠**，醒来后回到循环重新检查。若持锁睡眠，
所有并发 acquire 会被串行化，吞吐反而低于令牌桶应有的水平。
"""

from __future__ import annotations

import asyncio
from typing import Protocol


class RateLimiter(Protocol):
    """限速器接口。保留抽象以便将来换成 Redis 分布式实现。"""

    async def acquire(self) -> None: ...

    async def close(self) -> None: ...


class MemoryRateLimiter:
    """进程内令牌桶。多副本部署时各副本独立，不构成全局速率保障。"""

    def __init__(self, rate: int = 8, burst: int | None = None) -> None:
        if rate <= 0:
            raise ValueError("rate 必须为正数")
        self.rate = float(rate)
        self.capacity = float(burst if burst is not None else rate)
        self._tokens = self.capacity
        self._updated_at = asyncio.get_running_loop().time()
        self._lock = asyncio.Lock()
        self._closed = False

    def _refill(self) -> None:
        now = asyncio.get_running_loop().time()
        elapsed = now - self._updated_at
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            self._updated_at = now

    async def acquire(self) -> None:
        """取一枚令牌；不足则睡到该枚令牌攒够，再回到循环重新检查。

        之所以要回到循环而不是睡完就返回：等待期间别人可能已经取走了那枚
        令牌，必须重新核算延迟。也因此才能真正并发——锁在睡眠开始前就已释放。
        """
        while not self._closed:
            delay = 0.0
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                # 缺 (1 - tokens) 枚，按 rate 折算成秒数
                delay = (1.0 - self._tokens) / self.rate
                self._tokens = 0.0
            # 锁外睡眠：并发调用者在此期间不会互相排队
            await asyncio.sleep(delay)

        raise RuntimeError("限速器已关闭")

    async def close(self) -> None:
        """幂等。正在睡眠的等待者会在醒来时发现已关闭并抛出。"""
        async with self._lock:
            self._closed = True
