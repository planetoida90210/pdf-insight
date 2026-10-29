"""In-memory request limits: a sliding window per client IP and a global daily cap."""

import ipaddress
import math
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, date, datetime

from starlette.requests import Request


class SlidingWindowLimiter:
    """Allows `limit` hits per key within any `window` seconds."""

    def __init__(
        self, limit: int, window: float = 60, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.limit = limit
        self.window = window
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str) -> int | None:
        """Records a hit; returns None when allowed, else seconds until the next free slot."""
        now = self.clock()
        self._prune(now)
        hits = self._hits.setdefault(key, deque())
        if len(hits) >= self.limit:
            return max(1, math.ceil(hits[0] + self.window - now))
        hits.append(now)
        return None

    def _prune(self, now: float) -> None:
        for key in list(self._hits):
            hits = self._hits[key]
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if not hits:
                del self._hits[key]


class DailyCounter:
    """Global cap per UTC day; protects the LLM budget regardless of client IPs."""

    def __init__(self, limit: int, today: Callable[[], date] = lambda: datetime.now(UTC).date()):
        self.limit = limit
        self.today = today
        self._day = today()
        self._count = 0

    def hit(self) -> bool:
        day = self.today()
        if day != self._day:
            self._day, self._count = day, 0
        if self._count >= self.limit:
            return False
        self._count += 1
        return True


# DigitalOcean App Platform puts the client address in this header. Its X-Forwarded-For names
# the DigitalOcean ingress, and the first entries of that header come from the client.
CLIENT_IP_HEADER = "do-connecting-ip"


def client_ip(request: Request) -> str:
    """The rate-limit key: App Platform's client address, else the TCP peer (local runs)."""
    peer = request.client.host if request.client else "unknown"
    address = request.headers.get(CLIENT_IP_HEADER) or peer
    try:
        ip = ipaddress.ip_address(address.strip())
    except ValueError:
        return address
    # An IPv6 subscriber usually holds a whole /64, so the prefix is one client.
    return str(ipaddress.ip_network(f"{ip}/64", strict=False)) if ip.version == 6 else str(ip)
