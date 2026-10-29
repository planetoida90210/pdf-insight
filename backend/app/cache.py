"""In-memory store for extractions between /api/extract and /api/analyze."""

import time
from collections.abc import Callable


class TtlCache[V]:
    """In-memory store with per-entry expiry; the oldest entry goes once `max_items` is hit."""

    def __init__(
        self, ttl: float, max_items: int = 100, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.ttl = ttl
        self.max_items = max_items
        self.clock = clock
        self._items: dict[str, tuple[float, V]] = {}

    def set(self, key: str, value: V) -> None:
        self._evict_expired()
        self._items.pop(key, None)
        while len(self._items) >= self.max_items:
            del self._items[next(iter(self._items))]
        self._items[key] = (self.clock() + self.ttl, value)

    def get(self, key: str) -> V | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        expires, value = entry
        if expires <= self.clock():
            del self._items[key]
            return None
        return value

    def _evict_expired(self) -> None:
        now = self.clock()
        for key in [k for k, (expires, _) in self._items.items() if expires <= now]:
            del self._items[key]
