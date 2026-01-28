"""Global pytest configuration and fixtures."""

import asyncio
import sys
import threading
import traceback
from contextlib import asynccontextmanager

import logging

import pytest


def fake_transaction_manager():
    """Return a fake transaction manager that yields a dummy session.

    Use in unit tests to cover service code paths that use
    async with self.transaction_manager.transaction() as session.
    In-memory repos accept session= and ignore it.
    """

    @asynccontextmanager
    async def _tx():
        yield object()

    class FakeTM:
        def transaction(self):
            return _tx()

    return FakeTM()


@pytest.fixture
def fake_tm():
    """Pytest fixture that provides a fake transaction manager."""
    return fake_transaction_manager()


_TRACKED_ASYNC_ENGINES: list[object] = []


@pytest.fixture(scope="session", autouse=True)
def _track_and_dispose_async_engines() -> None:
    """Track AsyncEngines created during tests and dispose them on teardown.

    When using `sqlite+aiosqlite`, each connection can spawn a worker thread.
    If an `AsyncEngine` isn't disposed, Python may hang during interpreter
    shutdown while waiting for those threads to finish.
    """

    from ugc_bot.infrastructure.db import session as session_mod

    mp = pytest.MonkeyPatch()
    original_create = session_mod.create_async_db_engine

    def _create_async_db_engine_tracked(*args, **kwargs):  # type: ignore[no-untyped-def]
        engine = original_create(*args, **kwargs)
        _TRACKED_ASYNC_ENGINES.append(engine)
        return engine

    mp.setattr(session_mod, "create_async_db_engine", _create_async_db_engine_tracked)
    try:
        yield
    finally:
        mp.undo()
        if not _TRACKED_ASYNC_ENGINES:
            return
        loop = asyncio.new_event_loop()
        try:
            for engine in list(_TRACKED_ASYNC_ENGINES):
                try:
                    loop.run_until_complete(engine.dispose())
                except Exception:
                    # Diagnostics will be printed in `pytest_sessionfinish`.
                    pass
        finally:
            loop.close()


@pytest.fixture(autouse=True)
def _silence_noisy_library_loggers() -> None:
    """Reduce noise from libraries during tests.

    Some tests enable DEBUG logging globally. When that happens, low-level
    libraries like `aiosqlite` start emitting connection lifecycle logs, which
    can be confusing and make test output look "stuck" during interpreter
    shutdown.
    """

    logging.getLogger("aiosqlite").setLevel(logging.WARNING)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Dump diagnostics if non-daemon threads are still alive.

    If the process hangs after pytest prints the summary and you see
    `KeyboardInterrupt` in `threading._shutdown`, it usually means some
    non-daemon thread is still running (e.g. a ThreadPoolExecutor worker).
    This hook prints the remaining threads and their stack traces.
    """

    _ = session, exitstatus

    threads = [
        t
        for t in threading.enumerate()
        if t.is_alive() and t is not threading.main_thread() and not t.daemon
    ]
    if not threads:
        return

    print(
        "\n=== pytest diagnostic: non-daemon threads still alive ===", file=sys.stderr
    )
    if _TRACKED_ASYNC_ENGINES:
        print(
            f"(tracked AsyncEngines created: {len(_TRACKED_ASYNC_ENGINES)})",
            file=sys.stderr,
        )
    for t in threads:
        print(
            f"- name={t.name!r} ident={t.ident} daemon={t.daemon}",
            file=sys.stderr,
        )

    frames = sys._current_frames()
    for t in threads:
        if t.ident is None:
            continue
        frame = frames.get(t.ident)
        if frame is None:
            continue
        print(f"\n--- stack for thread {t.name!r} ({t.ident}) ---", file=sys.stderr)
        for line in traceback.format_stack(frame):
            print(line.rstrip("\n"), file=sys.stderr)
