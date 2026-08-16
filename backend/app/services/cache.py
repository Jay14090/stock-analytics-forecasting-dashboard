"""A small thread-safe TTL cache.

Market data is read far more often than it changes, and Yahoo Finance rate
limits aggressively, so every upstream call goes through here. Deliberately
in-process: one gunicorn worker per cache is fine at this scale, and it keeps
the deployment to a single service. Swapping in Redis means reimplementing
``get``/``set`` and nothing else.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(slots=True)
class _Entry:
    value: Any
    expires_at: float

    def is_fresh(self, now: float) -> bool:
        return now < self.expires_at


class TTLCache:
    """LRU cache with per-entry expiry.

    Eviction is least-recently-used once ``max_entries`` is reached, so a
    long-running process that touches thousands of symbols keeps only the hot
    ones resident.
    """

    def __init__(self, max_entries: int = 512) -> None:
        self._max_entries = max(1, max_entries)
        self._store: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Any | None:
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            if not entry.is_fresh(now):
                del self._store[key]
                self._misses += 1
                return None
            self._store.move_to_end(key)
            self._hits += 1
            return entry.value

    def set(self, key: str, value: Any, ttl: float) -> None:
        if ttl <= 0:
            return
        with self._lock:
            self._store[key] = _Entry(value=value, expires_at=time.monotonic() + ttl)
            self._store.move_to_end(key)
            while len(self._store) > self._max_entries:
                evicted, _ = self._store.popitem(last=False)
                logger.debug("cache_evict key=%s", evicted)

    def get_or_set(self, key: str, ttl: float, factory: Callable[[], T]) -> T:
        """Return the cached value, otherwise call ``factory`` and store it.

        ``factory`` runs outside the lock: it performs network I/O, and holding
        the lock across it would serialise every request in the process. A
        concurrent duplicate fetch is cheaper than that contention.
        """
        cached = self.get(key)
        if cached is not None:
            return cached
        value = factory()
        self.set(key, value, ttl)
        return value

    def invalidate(self, prefix: str = "") -> int:
        """Drop entries whose key starts with ``prefix`` (all keys if empty)."""
        with self._lock:
            if not prefix:
                count = len(self._store)
                self._store.clear()
                return count
            doomed = [k for k in self._store if k.startswith(prefix)]
            for key in doomed:
                del self._store[key]
            return len(doomed)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            return {
                "entries": len(self._store),
                "max_entries": self._max_entries,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total, 4) if total else 0.0,
            }


#: Process-wide cache shared by every market-data call.
market_cache = TTLCache()
