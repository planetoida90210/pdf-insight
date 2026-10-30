"""In-memory request limits: a sliding window per client IP and daily caps on LLM calls."""

import ipaddress
import math
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from ctypes import c_int
from dataclasses import dataclass
from datetime import UTC, date, datetime

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


# Takes one LLM call from a daily budget; False once the budget is used up.
Charge = Callable[[], bool]
# An extraction worker's vision calls run in threads; each worker process has its own lock.
_ALLOWANCE_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class Allowance:
    """The LLM calls one extraction worker may make, counted down in shared memory. Only the
    worker writes it, so no lock is shared with the web process."""

    left: c_int

    def hit(self) -> bool:
        with _ALLOWANCE_LOCK:
            if self.left.value <= 0:
                return False
            self.left.value -= 1
            return True


class DailyLlmLimits:
    """Caps on LLM calls per UTC day: one for the service, so a bill cannot run away, and one
    per client IP, so one client cannot use up the day for everyone.

    The counts live in the web process only. An extraction worker gets an allowance taken out
    of them before it starts: a worker killed at its deadline cannot leave a lock held.
    """

    def __init__(
        self, service_limit: int, client_limit: int, today: Callable[[], date] = utc_today
    ) -> None:
        self.service_limit = service_limit
        self.client_limit = client_limit
        self.today = today
        self._lock = threading.Lock()
        self._day = today()
        self._service = 0
        self._clients: dict[str, int] = {}

    def hit(self, client: str) -> bool:
        return self._take(client, 1) == 1

    @contextmanager
    def allowance(self, client: str, calls: int) -> Iterator[Allowance]:
        """Up to `calls` of `client`'s calls set aside for an extraction worker; the ones it
        leaves, also when it is killed, are given back when it ends."""
        day = self.today()
        allowance = Allowance(CONTEXT.RawValue("i", self._take(client, calls)))
        try:
            yield allowance
        finally:
            self._give_back(client, allowance.left.value, day)

    def _take(self, client: str, calls: int) -> int:
        with self._lock:
            if (day := self.today()) != self._day:
                self._day, self._service, self._clients = day, 0, {}
            used = self._clients.get(client, 0)
            free = min(self.service_limit - self._service, self.client_limit - used)
            granted = max(0, min(calls, free))
            self._service += granted
            self._clients[client] = used + granted
            return granted

    def _give_back(self, client: str, calls: int, day: date) -> None:
        with self._lock:
            # Yesterday's calls are no longer counted.
            if day == self._day:
                self._service -= calls
                self._clients[client] -= calls


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
