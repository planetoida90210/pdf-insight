import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.errors import ApiError, ErrorCode
from app.worker import run_isolated

linux_only = pytest.mark.skipif(sys.platform != "linux", reason="memory caps are Linux-only")


def too_many_pages() -> None:
    raise ApiError(ErrorCode.TOO_MANY_PAGES, max_pages=3)


def spawn_and_die(marker: Path) -> None:
    subprocess.Popen(["sh", "-c", 'sleep 1 && touch "$0"', str(marker)])
    os._exit(1)


def run(task: object, *args: object, timeout: float = 30, memory_mb: int = 1024) -> object:
    return run_isolated(task, *args, timeout=timeout, memory_mb=memory_mb)  # type: ignore[arg-type]


def error_of(task: object, *args: object, **limits: float) -> ApiError:
    with pytest.raises(ApiError) as raised:
        run(task, *args, **limits)  # type: ignore[arg-type]
    return raised.value


def test_returns_the_task_result() -> None:
    assert run(sorted, [3, 1, 2]) == [1, 2, 3]


def test_task_errors_keep_code_and_message() -> None:
    error = error_of(too_many_pages)
    assert (error.code, error.message) == (
        ErrorCode.TOO_MANY_PAGES,
        "Dokument ma za dużo stron. Maksymalna liczba stron to 3.",
    )


def test_child_is_killed_at_the_deadline() -> None:
    started = time.monotonic()
    assert error_of(time.sleep, 30, timeout=0.5).code == ErrorCode.TIMEOUT
    assert time.monotonic() - started < 10


def test_subprocesses_are_killed_with_the_child(tmp_path: Path) -> None:
    marker = tmp_path / "subprocess-finished"
    assert error_of(spawn_and_die, marker).code == ErrorCode.INVALID_PDF
    time.sleep(1.5)
    assert not marker.exists()


def test_child_that_dies_reports_invalid_pdf() -> None:
    assert error_of(os._exit, 1).code == ErrorCode.INVALID_PDF


@linux_only
def test_allocation_past_the_cap_reports_invalid_pdf() -> None:
    assert error_of(bytearray, 2 << 30, memory_mb=512).code == ErrorCode.INVALID_PDF
