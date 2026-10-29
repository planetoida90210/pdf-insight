from datetime import date

from starlette.requests import Request

from app.ratelimit import DailyLlmLimits, LlmBudget, SlidingWindowLimiter, client_ip
from app.worker import run_isolated


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_sliding_window_blocks_then_frees_slot() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=2, window=60, clock=clock)
    assert limiter.hit("a") is None
    clock.now += 10
    assert limiter.hit("a") is None
    assert limiter.hit("a") == 50
    assert limiter.hit("b") is None
    clock.now += 50
    assert limiter.hit("a") is None


def test_sliding_window_forgets_idle_keys() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=1, window=60, clock=clock)
    limiter.hit("a")
    clock.now += 61
    limiter.hit("b")
    assert set(limiter._hits) == {"b"}


def test_daily_llm_limits_cap_each_client_and_the_service() -> None:
    day = [date(2026, 10, 29)]
    limits = DailyLlmLimits(service_limit=3, client_limit=2, today=lambda: day[0])
    a = limits.budget_for("a")
    assert [a.hit(), a.hit(), a.hit()] == [True, True, False]
    assert limits.budget_for("a").hit() is False
    b = limits.budget_for("b")
    assert [b.hit(), b.hit()] == [True, False]
    day[0] = date(2026, 10, 30)
    assert limits.budget_for("a").hit() is True


def spend(budget: LlmBudget, calls: int) -> list[bool]:
    return [budget.hit() for _ in range(calls)]


def test_worker_process_draws_from_the_same_client_budget() -> None:
    limits = DailyLlmLimits(service_limit=100, client_limit=3)
    used = run_isolated(spend, limits.budget_for("a"), 2, timeout=30, memory_mb=1024)
    assert used == [True, True]
    assert spend(limits.budget_for("a"), 2) == [True, False]


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
