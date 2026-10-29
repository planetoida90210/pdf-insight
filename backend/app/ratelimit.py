"""In-memory request limits: a sliding window per client IP and daily caps on LLM calls."""

import ipaddress
import math
import time
from collections import deque
from collections.abc import Callable
from ctypes import c_int
from dataclasses import dataclass
from datetime import UTC, date, datetime
from multiprocessing.sharedctypes import Synchronized

from starlette.requests import Request

from app.worker import CONTEXT


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


def utc_today() -> date:
    return datetime.now(UTC).date()


@dataclass(frozen=True, slots=True)
class LlmBudget:
    """The LLM calls one client may still make today.

    The counts live in shared memory and the budget is passed to the extraction worker started
    for the request, so the worker's vision calls draw from it as well.
    """

    service: "Synchronized[int]"  # calls made today by every client; its lock guards both
    client: c_int  # calls made today by this client
    service_limit: int
    client_limit: int

    def hit(self) -> bool:
        with self.service.get_lock():
            if self.service.value >= self.service_limit or self.client.value >= self.client_limit:
                return False
            self.service.value += 1
            self.client.value += 1
            return True


class DailyLlmLimits:
    """Caps on LLM calls per UTC day: one for the service, so a bill cannot run away, and one
    per client IP, so one client cannot use up the day for everyone. Lives in the web process."""

    def __init__(
        self, service_limit: int, client_limit: int, today: Callable[[], date] = utc_today
    ) -> None:
        self.service_limit = service_limit
        self.client_limit = client_limit
        self.today = today
        self._day = today()
        self._service = CONTEXT.Value("i", 0)
        # No lock per client: the service count's lock guards them all.
        self._clients: dict[str, c_int] = {}

    def budget_for(self, client: str) -> LlmBudget:
        with self._service.get_lock():
            if (day := self.today()) != self._day:
                self._day, self._service.value, self._clients = day, 0, {}
            if client not in self._clients:
                self._clients[client] = CONTEXT.Value("i", 0, lock=False)
            counter = self._clients[client]
        return LlmBudget(self._service, counter, self.service_limit, self.client_limit)


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
