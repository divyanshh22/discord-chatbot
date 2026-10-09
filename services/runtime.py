from __future__ import annotations

import time
from collections import deque

from config import Config


class RateLimiter:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._last_user: dict[int, float] = {}
        self._last_global: float = 0.0
        self._minute: deque[float] = deque(
            maxlen=max(config.max_responses_per_minute * 4, 64)
        )

    def _prune(self, now: float) -> None:
        window = now - 60.0
        while self._minute and self._minute[0] < window:
            self._minute.popleft()

    def user_ready(self, user_id: int) -> bool:
        last = self._last_user.get(user_id)
        if last is None:
            return True
        return (time.monotonic() - last) >= self._config.user_cooldown

    def user_retry_after(self, user_id: int) -> float:
        last = self._last_user.get(user_id)
        if last is None:
            return 0.0
        return max(0.0, self._config.user_cooldown - (time.monotonic() - last))

    def global_ready(self) -> bool:
        return (time.monotonic() - self._last_global) >= self._config.global_cooldown

    def minute_ok(self) -> bool:
        now = time.monotonic()
        self._prune(now)
        return len(self._minute) < self._config.max_responses_per_minute

    def register(self, user_id: int | None) -> None:
        now = time.monotonic()
        self._last_global = now
        self._minute.append(now)
        if user_id is not None:
            self._last_user[user_id] = now

    def prune_users(self, max_entries: int = 5000) -> None:
        if len(self._last_user) <= max_entries:
            return
        cutoff = time.monotonic() - max(self._config.user_cooldown * 10, 600)
        stale = [uid for uid, ts in self._last_user.items() if ts < cutoff]
        for uid in stale:
            self._last_user.pop(uid, None)


class FailureBackoff:
    def __init__(self, cooldown: float = 30.0) -> None:
        self._cooldown = cooldown
        self._last_notice = 0.0

    def should_notify(self) -> bool:
        if (time.monotonic() - self._last_notice) >= self._cooldown:
            self._last_notice = time.monotonic()
            return True
        return False
