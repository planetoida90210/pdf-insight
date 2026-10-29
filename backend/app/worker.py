"""Untrusted PDFs are parsed in a child process with a memory cap that is killed at its deadline."""

import contextlib
import logging
import multiprocessing
import os
import resource
import signal
from collections.abc import Callable
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any, cast

from app.config import configure_logging, error_frames
from app.errors import ApiError, ErrorCode

logger = logging.getLogger(__name__)

# Children fork from a single-threaded server that has the parsing modules imported already,
# not from the threaded web process.
CONTEXT = multiprocessing.get_context("forkserver")
CONTEXT.set_forkserver_preload(["app.extraction"])


def run_isolated[T](task: Callable[..., T], *args: Any, timeout: float, memory_mb: int) -> T:
    """`task(*args)` in a child process; its ApiError is re-raised here.

    TIMEOUT when the deadline passes, INVALID_PDF when the file needs more memory than allowed.
    """
    receiver, sender = CONTEXT.Pipe(duplex=False)
    child = CONTEXT.Process(target=_run, args=(sender, memory_mb, task, args), daemon=True)
    child.start()
    sender.close()
    try:
        if not receiver.poll(timeout):
            logger.warning("extraction worker killed at the %ss deadline", timeout)
            raise ApiError(ErrorCode.TIMEOUT)
        ok, value = receiver.recv()
    except EOFError as error:
        # Killed by the kernel (exit code -9) or crashed in native code before it could answer.
        child.join(1)
        logger.warning("extraction worker exited without a result, exit code %s", child.exitcode)
        raise ApiError(ErrorCode.INVALID_PDF) from error
    finally:
        # The child leads its own process group, so an OCR subprocess dies with it and cannot
        # outlive the extraction slot. A group that has already exited answers ESRCH, or EPERM
        # on macOS while the child is a zombie.
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(cast(int, child.pid), signal.SIGKILL)
        child.kill()
        child.join()
        receiver.close()
    if not ok:
        raise value
    return value  # type: ignore[no-any-return]


def _run(sender: Connection, memory_mb: int, task: Callable[..., Any], args: Any) -> None:
    os.setpgrp()
    configure_logging()
    _limit_memory(memory_mb * 1024 * 1024)
    try:
        sender.send((True, task(*args)))
    except ApiError as error:
        sender.send((False, error))
    except MemoryError:
        logger.warning("extraction worker hit the %s MiB memory cap", memory_mb)
        sender.send((False, ApiError(ErrorCode.INVALID_PDF)))
    except Exception as error:
        logger.error("extraction worker failed: %s\n%s", type(error).__name__, error_frames(error))
        sender.send((False, ApiError(ErrorCode.INTERNAL)))


def _limit_memory(limit: int) -> None:
    """Allocations past `limit` raise MemoryError; if the container runs out first, the kernel
    kills this child rather than the web process. Both are Linux-only, so local macOS runs go
    without them."""
    try:
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ValueError, OSError):
        logger.warning("extraction worker runs without a memory cap")
    with contextlib.suppress(OSError):
        Path("/proc/self/oom_score_adj").write_text("1000")
