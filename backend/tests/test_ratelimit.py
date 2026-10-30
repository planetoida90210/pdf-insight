import os
from datetime import date

import pytest
from starlette.requests import Request

from app.errors import ApiError
from app.ratelimit import Allowance, DailyLlmLimits, SlidingWindowLimiter, client_ip
from app.worker import run_isolated
from tests.fakes import FakeClock


def test_sliding_window_blocks_then_frees_slot() -> None:
    clock = FakeClock(1000.0)
    limiter = SlidingWindowLimiter(limit=2, window=60, clock=clock)
    assert limiter.hit("a") is None
    clock.now += 10
    assert limiter.hit("a") is None
    assert limiter.hit("a") == 50
    assert limiter.hit("b") is None
    clock.now += 50
    assert limiter.hit("a") is None


def test_sliding_window_forgets_idle_keys() -> None:
    clock = FakeClock(1000.0)
    limiter = SlidingWindowLimiter(limit=1, window=60, clock=clock)
    limiter.hit("a")
    clock.now += 61
    limiter.hit("b")
    assert set(limiter._hits) == {"b"}


def test_daily_llm_limits_cap_each_client_and_the_service() -> None:
    day = [date(2026, 10, 29)]
    limits = DailyLlmLimits(service_limit=3, client_limit=2, today=lambda: day[0])
    assert [limits.hit("a"), limits.hit("a"), limits.hit("a")] == [True, True, False]
    assert [limits.hit("b"), limits.hit("b")] == [True, False]
    day[0] = date(2026, 10, 30)
    assert limits.hit("a") is True


def spend_then_die(allowance: Allowance, calls: int) -> None:
    for _ in range(calls):
        allowance.hit()
    os._exit(1)


def test_a_killed_worker_keeps_the_calls_it_made_and_returns_the_rest() -> None:
    limits = DailyLlmLimits(service_limit=100, client_limit=5)
    with limits.allowance("a", 4) as allowance, pytest.raises(ApiError):
        run_isolated(spend_then_die, allowance, 3, timeout=30, memory_mb=1024)
    assert [limits.hit("a"), limits.hit("a"), limits.hit("a")] == [True, True, False]


def test_an_allowance_given_back_after_midnight_leaves_the_new_day_alone() -> None:
    day = [date(2026, 10, 29)]
    limits = DailyLlmLimits(service_limit=100, client_limit=2, today=lambda: day[0])
    with limits.allowance("a", 2):
        day[0] = date(2026, 10, 30)
        assert limits.hit("a") is True
    assert [limits.hit("a"), limits.hit("a")] == [True, False]


def make_request(headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": ("10.0.0.1", 1234),
        }
    )


def test_client_ip_reads_app_platform_header_not_forwarded_for() -> None:
    headers = {"X-Forwarded-For": "6.6.6.6, 10.244.0.7", "DO-Connecting-IP": "1.2.3.4"}
    assert client_ip(make_request(headers)) == "1.2.3.4"
    assert client_ip(make_request({"X-Forwarded-For": "6.6.6.6"})) == "10.0.0.1"


def test_client_ip_groups_ipv6_by_64_prefix() -> None:
    first = make_request({"DO-Connecting-IP": "2001:db8:1:2::1"})
    second = make_request({"DO-Connecting-IP": "2001:db8:1:2:ffff::9"})
    assert client_ip(first) == client_ip(second) == "2001:db8:1:2::/64"
