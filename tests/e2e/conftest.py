"""E2E test fixtures: test database, admin server, Playwright, Telegram."""

# Register Telegram E2E fixtures from telegram_client so e2e_telegram tests see them
pytest_plugins = ["tests.e2e.telegram_client"]

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from ugc_bot.infrastructure.db.base import Base


def pytest_sessionstart(session: pytest.Session) -> None:
    """Clean DB users before E2E Telegram tests when E2E_DATABASE_URL is set."""
    if not os.environ.get("E2E_DATABASE_URL"):
        return
    try:
        items = session.items
    except Exception:
        items = []
    has_telegram = any(
        item.get_closest_marker("e2e_telegram") is not None for item in items
    )
    if not has_telegram:
        return
    root = Path(__file__).resolve().parent.parent.parent
    script = root / "scripts" / "clean_e2e_users.py"
    if not script.exists():
        return
    subprocess.run(
        [sys.executable, str(script)],
        cwd=str(root),
        env=os.environ.copy(),
        check=False,
        capture_output=True,
    )


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
