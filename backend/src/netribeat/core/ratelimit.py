"""Fixed-window counters for rate limiting. Redis in dev/prod; in-memory for unit tests."""

from __future__ import annotations

from typing import Protocol

from redis.asyncio import Redis

from netribeat.clock import Clock

KEY_PREFIX = "nb:rl:"


class RateLimiter(Protocol):
    async def count(self, key: str) -> int: ...
    async def increment(self, key: str, window_s: int) -> int: ...
    async def reset(self, key: str) -> None: ...


class RedisRateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def count(self, key: str) -> int:
        value = await self._redis.get(KEY_PREFIX + key)
        return int(value) if value is not None else 0

    async def increment(self, key: str, window_s: int) -> int:
        full = KEY_PREFIX + key
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(full)
            pipe.expire(full, window_s, nx=True)  # window starts at the first hit
            result = await pipe.execute()
        return int(result[0])

    async def reset(self, key: str) -> None:
        await self._redis.delete(KEY_PREFIX + key)


class MemoryRateLimiter:
    """Single-process limiter driven by an injectable clock (tests)."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._data: dict[str, tuple[int, float]] = {}

    def _live(self, key: str) -> tuple[int, float] | None:
        entry = self._data.get(key)
        if entry and entry[1] > self._clock.now().timestamp():
            return entry
        self._data.pop(key, None)
        return None

    async def count(self, key: str) -> int:
        entry = self._live(key)
        return entry[0] if entry else 0

    async def increment(self, key: str, window_s: int) -> int:
        entry = self._live(key)
        if entry:
            self._data[key] = (entry[0] + 1, entry[1])
        else:
            self._data[key] = (1, self._clock.now().timestamp() + window_s)
        return self._data[key][0]

    async def reset(self, key: str) -> None:
        self._data.pop(key, None)
