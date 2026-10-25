from __future__ import annotations

import uuid

import pytest
from redis.asyncio import Redis

from netribeat.clock import FrozenClock
from netribeat.core.ratelimit import MemoryRateLimiter, RedisRateLimiter
from tests.conftest import START


async def test_memory_limiter_counts_and_expires() -> None:
    clock = FrozenClock(START)
    rl = MemoryRateLimiter(clock)
    assert [await rl.increment("k", 60) for _ in range(3)] == [1, 2, 3]
    clock.advance(seconds=59)
    assert await rl.count("k") == 3
    clock.advance(seconds=2)
    assert await rl.count("k") == 0
    assert await rl.increment("k", 60) == 1


async def test_memory_limiter_reset() -> None:
    rl = MemoryRateLimiter(FrozenClock(START))
    await rl.increment("k", 60)
    await rl.reset("k")
    assert await rl.count("k") == 0


@pytest.mark.redis
async def test_redis_limiter_window_and_reset() -> None:
    redis = Redis.from_url("redis://localhost:6379/15", decode_responses=True)
    try:
        await redis.ping()
    except Exception:  # pragma: no cover - environment without Redis
        pytest.skip("Redis not available")
    rl = RedisRateLimiter(redis)
    key = f"test:{uuid.uuid4()}"
    try:
        assert await rl.increment(key, 30) == 1
        assert await rl.increment(key, 30) == 2
        assert await rl.count(key) == 2
        ttl = await redis.ttl("nb:rl:" + key)
        assert 0 < ttl <= 30  # window set once, on the first hit
        await rl.reset(key)
        assert await rl.count(key) == 0
    finally:
        await redis.delete("nb:rl:" + key)
        await redis.aclose()
