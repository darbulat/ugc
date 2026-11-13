"""E2E test fixtures: test database, admin server, Playwright, Telegram."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

import pytest
from sqlalchemy import create_engine

from tests.helpers.financial_environment import require_synthetic_e2e
from tests.helpers.sqlite_schema import legacy_sqlite_tables
from ugc_bot.infrastructure.db.base import Base

_MINIAPP_CLASS_ORDER = {
    "TestMiniAppAdvertiser": 0,
    "TestMiniAppBlogger": 1,
    "TestMiniAppNavigation": 2,
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Order e2e_telegram and miniapp tests."""
    # --- Telegram e2e ordering (existing) ---
    telegram_items = [
        (i, item)
        for i, item in enumerate(items)
        if item.get_closest_marker("e2e_telegram") is not None
    ]
    if telegram_items:

        def order_key(entry: tuple[int, pytest.Item]) -> tuple[int, int]:
            idx, item = entry
            nodeid = item.nodeid
            if "profile_update" in nodeid:
                return (1, idx)
            return (0, idx)

        telegram_items.sort(key=order_key)
        reordered_ids = [item.nodeid for _, item in telegram_items]
        id_to_item = {item.nodeid: item for item in items}
        remaining = [item for item in items if item.nodeid not in reordered_ids]
        items[:] = remaining + [id_to_item[nid] for nid in reordered_ids]

    # --- Miniapp e2e ordering ---
    miniapp_items = []
    for i, item in enumerate(items):
        cls = getattr(item, "cls", None)
        if cls and cls.__name__ in _MINIAPP_CLASS_ORDER:
            miniapp_items.append((i, item))
    if not miniapp_items:
        return

    def miniapp_order_key(entry: tuple[int, pytest.Item]) -> tuple[int, int]:
        idx, item = entry
        cls = getattr(item, "cls", None)
        cls_order = _MINIAPP_CLASS_ORDER.get(cls.__name__, 99) if cls else 99
        return (cls_order, idx)

    miniapp_items.sort(key=miniapp_order_key)
    reordered_ids = [item.nodeid for _, item in miniapp_items]
    id_to_item = {item.nodeid: item for item in items}
    remaining = [item for item in items if item.nodeid not in reordered_ids]
    items[:] = remaining + [id_to_item[nid] for nid in reordered_ids]


def pytest_sessionstart(session: pytest.Session) -> None:
    """Reject unsafe targets before any connection, script, or DELETE."""
    try:
        require_synthetic_e2e(os.environ)
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from None
    db_url = os.environ.get("E2E_DATABASE_URL")
    if not db_url:
        return

    # Existing telegram e2e cleanup
    try:
        items = session.items
    except Exception:
        items = []
    has_telegram = any(
        item.get_closest_marker("e2e_telegram") is not None for item in items
    )
    if has_telegram:
        root = Path(__file__).resolve().parent.parent.parent
        script = root / "scripts" / "clean_e2e_users.py"
        if script.exists():
            cmd = [sys.executable, str(script)]
            clean_telegram = os.environ.get("E2E_CLEAN_TELEGRAM", "").strip()
            if clean_telegram:
                cmd.extend(["--telegram", clean_telegram])
            subprocess.run(
                cmd,
                cwd=str(root),
                env=os.environ.copy(),
                check=False,
                capture_output=True,
            )

    # Miniapp e2e cleanup: delete test users by telegram_id
    miniapp_user_ids = []
    for role_ids in MINIAPP_TEST_USER_IDS.values():
        miniapp_user_ids.extend(str(uid) for uid in role_ids.values())
    if miniapp_user_ids:
        try:
            from sqlalchemy import text

            engine = create_engine(db_url)
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM users WHERE telegram_id = ANY(:ids)"),
                    {"ids": miniapp_user_ids},
                )
            engine.dispose()
        except Exception:
            pass  # Cleanup is best-effort


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Project root directory."""
    return Path(__file__).resolve().parent.parent.parent


def _use_external_server() -> bool:
    """True when E2E_BASE_URL is set (Docker Compose mode)."""
    require_synthetic_e2e(os.environ)
    return bool(os.environ.get("E2E_BASE_URL"))


@pytest.fixture(scope="session")
def test_database(
    project_root: Path, tmp_path_factory: pytest.TempPathFactory
) -> str:
    """Create temporary SQLite DB with schema for E2E tests (local mode)."""
    if _use_external_server():
        return ""  # not used
    db_dir = tmp_path_factory.mktemp("e2e_db")
    db_path = db_dir / "e2e.db"

    from ugc_bot.infrastructure.db import dispatch_control, models  # noqa: F401

    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    tables_to_create = legacy_sqlite_tables(Base.metadata)
    Base.metadata.create_all(bind=engine, tables=tables_to_create)
    engine.dispose()

    return f"sqlite:///{db_path}"


@pytest.fixture(scope="session")
def admin_server(test_database: str, project_root: Path, tmp_path_factory):
    """Start a private admin instance or use the configured Docker endpoint."""
    if _use_external_server():
        yield os.environ["E2E_BASE_URL"].strip()
        return
    env = os.environ.copy()
    env.update(
        {
            "BOT_TOKEN": "test-token",
            "DATABASE_URL": test_database,
            "ADMIN_USERNAME": "test_admin",
            "ADMIN_PASSWORD": "test_pass",
            "ADMIN_SECRET": "test_secret",
            "KAFKA_ENABLED": "false",
            "FEEDBACK_ENABLED": "false",
        }
    )
    server_log = tmp_path_factory.mktemp("admin_server") / "uvicorn.log"
    # Give the subprocess an already reserved listener.
    with socket.socket() as listener, server_log.open("w") as output:
        listener.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        fd = listener.fileno()
        proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import socket, sys, uvicorn; "
                "listener = socket.socket(fileno=int(sys.argv[1])); "
                "uvicorn.Server(uvicorn.Config('ugc_bot.admin.app:app'))"
                ".run(sockets=[listener])",
                str(fd),
            ],
            cwd=project_root,
            env=env,
            pass_fds=(fd,),
            stdout=subprocess.DEVNULL,
            stderr=output,
        )

    try:
        for _ in range(30):
            if proc.poll() is not None:
                break
            try:
                with urlopen(f"{url}/health", timeout=2):
                    break
            except OSError:
                time.sleep(0.5)
        else:
            raise RuntimeError(
                f"Admin server did not become ready. See {server_log}"
            )
        if proc.poll() is not None:
            raise RuntimeError(f"Admin server exited. See {server_log}")
        yield url
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


# --- Mini App E2E fixtures ---

from tests.e2e.miniapp_helpers import MINIAPP_TEST_USER_IDS  # noqa: E402


def _miniapp_base_url() -> str | None:
    require_synthetic_e2e(os.environ)
    return os.environ.get("E2E_MINIAPP_URL", "").strip() or None


def _miniapp_bot_token() -> str | None:
    return os.environ.get("E2E_BOT_TOKEN", "").strip() or None


@pytest.fixture(scope="session")
def miniapp_base_url() -> str:
    """Base URL for Mini App. Skips if E2E_MINIAPP_URL not set."""
    url = _miniapp_base_url()
    if not url:
        pytest.skip("E2E_MINIAPP_URL not set")
    return url


@pytest.fixture(scope="session")
def miniapp_bot_token() -> str:
    """Bot token for signing initData. Skips if E2E_BOT_TOKEN not set."""
    token = _miniapp_bot_token()
    if not token:
        pytest.skip("E2E_BOT_TOKEN not set")
    return token


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict) -> dict:  # type: ignore[type-arg]
    """Ignore HTTPS errors for self-signed certs in Docker."""
    return {**browser_context_args, "ignore_https_errors": True}


@pytest.fixture()
def miniapp_page(browser, miniapp_base_url):
    """Restrict the synthetic host to the configured local test app."""
    ctx = browser.new_context(ignore_https_errors=True)
    target = urlsplit(miniapp_base_url)

    def test_app_only(route):
        destination = urlsplit(route.request.url)
        if (destination.scheme, destination.netloc) == (
            target.scheme,
            target.netloc,
        ):
            route.continue_()
        else:
            route.abort()

    ctx.route("**/*", test_app_only)
    ctx.route(
        "**/telegram-web-app.js",
        lambda route: route.fulfill(
            status=200, body="", content_type="text/javascript"
        ),
    )
    page = ctx.new_page()
    yield page
    ctx.close()
