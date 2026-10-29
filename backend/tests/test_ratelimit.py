from datetime import date

from starlette.requests import Request

from app.ratelimit import DailyCounter, SlidingWindowLimiter, client_ip


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


def test_daily_counter_resets_next_day() -> None:
    day = [date(2026, 10, 29)]
    counter = DailyCounter(limit=2, today=lambda: day[0])
    assert counter.hit()
    assert counter.hit()
    assert not counter.hit()
    day[0] = date(2026, 10, 30)
    assert counter.hit()


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
