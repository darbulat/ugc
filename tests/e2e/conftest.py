"""E2E test fixtures: test database, admin server, Playwright, Telegram."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine

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
    """Clean DB users before E2E tests when E2E_DATABASE_URL is set."""
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

    # Miniapp e2e cleanup: delete test users by external_id
    miniapp_user_ids = []
    for role_ids in MINIAPP_TEST_USER_IDS.values():
        miniapp_user_ids.extend(str(uid) for uid in role_ids.values())
    if miniapp_user_ids:
        try:
            from sqlalchemy import text

            engine = create_engine(db_url)
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM users WHERE external_id = ANY(:ids)"),
                    {"ids": miniapp_user_ids},
                )
            engine.dispose()
        except Exception:
            pass  # Cleanup is best-effort


E2E_PORT = 8001
BASE_URL = f"http://127.0.0.1:{E2E_PORT}"
TABLES_TO_EXCLUDE = {"outbox_events", "blogger_profiles"}


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Project root directory."""
    return Path(__file__).resolve().parent.parent.parent


def _use_external_server() -> bool:
    """True when E2E_BASE_URL is set (Docker Compose mode)."""
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

    from ugc_bot.infrastructure.db import models  # noqa: F401

    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    tables_to_create = [
        t
        for t in Base.metadata.tables.values()
        if t.name not in TABLES_TO_EXCLUDE
    ]
    Base.metadata.create_all(bind=engine, tables=tables_to_create)
    engine.dispose()

    return f"sqlite:///{db_path}"


@pytest.fixture(scope="session")
def admin_server(test_database: str, project_root: Path):
    """Start admin uvicorn in subprocess (local). No-op in Docker."""
    if _use_external_server():
        yield
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

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "ugc_bot.admin.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(E2E_PORT),
        ],
        cwd=str(project_root),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    try:
        for _ in range(30):
            try:
                import urllib.request

                urllib.request.urlopen(f"{BASE_URL}/health", timeout=2)
                break
            except OSError:
                time.sleep(0.5)
        else:
            stderr = proc.stderr.read().decode() if proc.stderr else ""
            proc.terminate()
            proc.wait(timeout=5)
            raise RuntimeError(
                f"Admin server did not become ready. stderr:\n{stderr}"
            )
        yield
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="session")
def base_url() -> str:
    """Base URL for admin app (local or Docker)."""
    env_url = os.environ.get("E2E_BASE_URL", "").strip()
    return env_url if env_url else BASE_URL


# --- Mini App E2E fixtures ---

from tests.e2e.miniapp_helpers import MINIAPP_TEST_USER_IDS  # noqa: E402


def _miniapp_base_url() -> str | None:
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
    """Allow plain HTTP connections (Chromium HTTPS-First may upgrade them)."""
    return {**browser_context_args, "ignore_https_errors": True}
