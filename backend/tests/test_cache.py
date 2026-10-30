from app.cache import TtlCache
from tests.fakes import FakeClock


def test_entries_expire_after_ttl() -> None:
    clock = FakeClock()
    cache: TtlCache[str] = TtlCache(ttl=900, clock=clock)
    cache.set("id", "text")
    clock.now = 899
    assert cache.get("id") == "text"
    clock.now = 900
    assert cache.get("id") is None


def test_oldest_entry_evicted_when_full() -> None:
    cache: TtlCache[int] = TtlCache(ttl=60, max_items=2, clock=FakeClock())
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    assert cache.get("a") is None
    assert (cache.get("b"), cache.get("c")) == (2, 3)
