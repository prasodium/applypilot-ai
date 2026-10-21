"""Tiny in-process sliding-window rate limiter for sensitive endpoints (local single-user app; no external store needed)."""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request

from app.errors import AppError


class TooManyRequests(AppError):
    status_code = 429
    code = "rate_limited"


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window: float) -> None:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            raise TooManyRequests(f"Too many requests. Try again in {int(window)} seconds.")
        q.append(now)

    def reset(self) -> None:
        self._hits.clear()


def limit(name: str, per_minute: int):
    """FastAPI dependency factory: `Depends(limit('submit', 10))`."""

    def dep(request: Request) -> None:
        request.app.state.limiter.check(name, per_minute, 60.0)

    return dep
