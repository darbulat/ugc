"""Global pytest configuration and fixtures."""

# Set env vars before any imports that might trigger config (e.g. admin app)
import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ADMIN_USERNAME", "test_admin")
os.environ.setdefault("ADMIN_PASSWORD", "test_pass")
os.environ.setdefault("ADMIN_SECRET", "test_secret")

import asyncio
import contextlib
import sys
import threading
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

# Ensure project root on path so "tests.helpers" resolves from any cwd
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from tests.helpers.fakes import (  # noqa: E402
    FakeMessengerClient,
    clear_fake_registries,
)
from tests.helpers.repositories import (  # noqa: E402, F401
    advertiser_repo,
    blogger_repo,
    complaint_repo,
    country_repo,
    instagram_verification_repo,
    interaction_repo,
    offer_dispatch_repo,
    order_repo,
    outbox_repo,
    payment_repo,
    pricing_repo,
    repos,
    user_repo,
)
from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS  # noqa: E402
from ugc_bot.infrastructure.messenger.telegram.adapter import (  # noqa: E402
    TelegramEventAdapter,
)
from ugc_bot.logging_setup import suppress_noisy_loggers  # noqa: E402


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--require-financial-postgres",
        action="store_true",
        help="Require isolated financial PostgreSQL (fail instead of skip)",
    )


def pytest_configure(config: pytest.Config) -> None:
    from tests.helpers.financial_environment import (
        require_synthetic_e2e,
        require_test_database,
    )

    try:
        require_synthetic_e2e(os.environ)
        url = os.environ.get("FINANCIAL_TEST_DATABASE_URL")
        if url or config.getoption("--require-financial-postgres"):
            require_test_database(url)
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from None


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


@pytest.fixture
def issue_lock_manager():
    """In-memory lock manager for issue description (no Redis in tests)."""
    from ugc_bot.infrastructure.redis_lock import IssueDescriptionLockManager

    return IssueDescriptionLockManager(redis_url=None)


_TRACKED_ASYNC_ENGINES: list[object] = []
_TRACKED_SYNC_ENGINES: list[object] = []


@pytest.fixture(scope="session", autouse=True)
def _track_and_dispose_async_engines() -> None:
    """Track AsyncEngines created during tests and dispose them on teardown.

    When using `sqlite+aiosqlite`, each connection can spawn a worker thread.
    If an `AsyncEngine` isn't disposed, Python may hang during interpreter
    shutdown while waiting for those threads to finish.
    """

    from ugc_bot.infrastructure.db import session as session_mod

    mp = pytest.MonkeyPatch()
    original_create_async = session_mod.create_async_db_engine
    original_create_sync = session_mod.create_db_engine

    def _create_async_db_engine_tracked(*args, **kwargs):  # type: ignore[no-untyped-def]
        engine = original_create_async(*args, **kwargs)
        _TRACKED_ASYNC_ENGINES.append(engine)
        return engine

    def _create_db_engine_tracked(*args, **kwargs):  # type: ignore[no-untyped-def]
        engine = original_create_sync(*args, **kwargs)
        _TRACKED_SYNC_ENGINES.append(engine)
        return engine

    mp.setattr(
        session_mod, "create_async_db_engine", _create_async_db_engine_tracked
    )
    mp.setattr(session_mod, "create_db_engine", _create_db_engine_tracked)
    try:
        yield
    finally:
        mp.undo()
        for sync_engine in list(_TRACKED_SYNC_ENGINES):
            with contextlib.suppress(Exception):
                sync_engine.dispose()
        if _TRACKED_ASYNC_ENGINES:
            loop = asyncio.new_event_loop()
            try:
                for engine in list(_TRACKED_ASYNC_ENGINES):
                    with contextlib.suppress(Exception):
                        loop.run_until_complete(engine.dispose())
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
    suppress_noisy_loggers()


@pytest.fixture(autouse=True)
def _clear_fake_messenger_registries() -> None:
    """Clear fake message/callback registries between tests."""
    clear_fake_registries()


@pytest.fixture
def messenger_client() -> FakeMessengerClient:
    """Fake messenger client for handler tests."""
    return FakeMessengerClient()


@pytest.fixture
def event_adapter() -> TelegramEventAdapter:
    """Telegram event adapter for fake aiogram objects."""
    return TelegramEventAdapter()


@pytest.fixture
def config():
    """Load config from env (has market defaults)."""
    from ugc_bot.config import load_config

    return load_config()


class FakeBotTextsService:
    """BotTextsService stub; returns DEFAULT_TEXTS for 'ru' in handler tests."""

    def _text(self, key: str, locale: str | None) -> str:
        loc = locale or "ru"
        return DEFAULT_TEXTS.get(loc, {}).get(key, "")

    async def get(self, key: str, locale: str | None = None) -> str:
        return self._text(key, locale)

    async def get_many(
        self, keys: list[str], locale: str | None = None
    ) -> dict[str, str]:
        loc = locale or "ru"
        return {k: self._text(k, loc) for k in keys}


@pytest.fixture
def bot_texts_service() -> FakeBotTextsService:
    """Fake bot texts service for handler tests."""
    return FakeBotTextsService()


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
        "\n=== pytest diagnostic: non-daemon threads still alive ===",
        file=sys.stderr,
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
        print(
            f"\n--- stack for thread {t.name!r} ({t.ident}) ---",
            file=sys.stderr,
        )
        for line in traceback.format_stack(frame):
            print(line.rstrip("\n"), file=sys.stderr)
