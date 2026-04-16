from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass
class _CacheRow(Generic[T]):
    expires_at: float
    value: T


class TTLCache(Generic[T]):
    def __init__(self, ttl_seconds: int, max_entries: int) -> None:
        self.ttl_seconds = max(1, int(ttl_seconds))
        self.max_entries = max(8, int(max_entries))
        self._lock = threading.Lock()
        self._rows: dict[str, _CacheRow[T]] = {}

    def get(self, key: str) -> T | None:
        now = time.time()
        with self._lock:
            row = self._rows.get(key)
            if row is None:
                return None
            if row.expires_at <= now:
                self._rows.pop(key, None)
                return None
            return row.value

    def set(self, key: str, value: T) -> None:
        now = time.time()
        with self._lock:
            if len(self._rows) >= self.max_entries:
                oldest_key = min(self._rows.items(), key=lambda item: item[1].expires_at)[0]
                self._rows.pop(oldest_key, None)
            self._rows[key] = _CacheRow(expires_at=now + self.ttl_seconds, value=value)

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._rows)

