"""Small in-memory sliding-window rate limiter (per client IP + bucket).

Good enough for a single process / assignment. For multiple instances, back this with
Redis (or use an API gateway) so limits are shared.
"""
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class SlidingWindowLimiter:
    def __init__(self, window_seconds: float = 60.0):
        self.window = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int) -> float | None:
        """Return None if allowed, else seconds until a slot frees up."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= limit:
                return max(0.0, self.window - (now - q[0]))
            q.append(now)
            return None


def rate_limit(bucket: str, setting_name: str):
    def dep(request: Request) -> None:
        limit = getattr(request.app.state.settings, setting_name)
        client = request.client.host if request.client else "unknown"
        wait = request.app.state.limiter.check(f"{bucket}:{client}", limit)
        if wait is not None:
            raise HTTPException(
                status_code=429, detail="Rate limit exceeded", headers={"Retry-After": str(int(wait) + 1)}
            )

    return dep
