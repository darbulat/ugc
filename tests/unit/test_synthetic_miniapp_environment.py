"""The browser test app must never connect to a non-test database."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"E2E_TEST_ONLY": "1", "DATABASE_URL": "postgresql://x@db/ugc"},
        {
            "E2E_TEST_ONLY": "1",
            "DATABASE_URL": "postgresql://x@remote.example/ugc_test",
        },
        {
            "E2E_TEST_ONLY": "1",
            "DATABASE_URL": "postgresql://x@db_test/ugc_test?host=remote",
        },
        {
            "E2E_TEST_ONLY": "1",
            "DATABASE_URL": "postgresql://x@db_test/ugc_test",
            "E2E_BOT_TOKEN": "not-a-test-token",
        },
    ],
)
def test_synthetic_miniapp_refuses_unmarked_or_unsafe_targets(environment):
    from tests.helpers.synthetic_miniapp_server import require_test_app_database

    with pytest.raises(ValueError):
        require_test_app_database(environment)


@pytest.mark.parametrize("host", ["127.0.0.1", "db_test"])
def test_synthetic_miniapp_accepts_only_explicit_isolated_targets(host):
    from tests.helpers.synthetic_miniapp_server import require_test_app_database

    url = f"postgresql+psycopg://test:test@{host}/ugc_test"
    assert (
        require_test_app_database(
            {
                "E2E_TEST_ONLY": "1",
                "E2E_BOT_TOKEN": "test-token",
                "DATABASE_URL": url,
            }
        )
        == url
    )


@pytest.mark.parametrize(
    "url",
    [
        "not-a-database-url",
        "postgresql://x@db_test/ugc_test",
        "postgresql://x@db_test/ugc_test?options=-csearch_path%3Dpublic",
        "postgresql://x@remote.example/ugc_test?options=-csearch_path%3Dfinancial_test_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa%2Cpublic",
        "postgresql://x@db_test/ugc_test?options=-csearch_path%3Dfinancial_test_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa%2Cpublic&host=remote",
    ],
)
def test_synthetic_app_refuses_nonisolated_scoped_urls(url):
    from tests.helpers.synthetic_miniapp_server import require_private_schema

    with pytest.raises(ValueError):
        require_private_schema(url)


def test_synthetic_app_accepts_a_private_schema_url():
    from tests.helpers.synthetic_miniapp_server import require_private_schema

    url = (
        "postgresql+psycopg://x@db_test/ugc_test?options="
        "-csearch_path%3Dfinancial_test_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa%2Cpublic"
    )
    require_private_schema(url)


def test_seed_refuses_an_external_database_before_connecting():
    from tests.helpers.synthetic_miniapp_server import seed

    engine = SimpleNamespace(
        url=make_url(
            "postgresql://x@remote.example/ugc_test?options="
            "-csearch_path%3Dfinancial_test_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa%2Cpublic"
        )
    )
    with pytest.raises(ValueError, match="private test schema"):
        seed(engine)


def test_invalid_bind_is_rejected_before_opening_database(monkeypatch):
    from tests.helpers import synthetic_miniapp_server as server

    monkeypatch.setenv("E2E_TEST_ONLY", "1")
    monkeypatch.setenv("E2E_BOT_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x@db_test/ugc_test")
    monkeypatch.setenv("SYNTHETIC_E2E_BIND", "remote.example")

    def unexpected_connection(_):
        raise AssertionError("database_must_not_be_opened")

    monkeypatch.setattr(
        server, "isolated_financial_database", unexpected_connection
    )
    with pytest.raises(ValueError, match="bind address"):
        server.main()


def test_synthetic_config_ignores_host_environment_and_dotenv(
    monkeypatch, tmp_path
):
    from tests.helpers.synthetic_miniapp_server import build_test_config

    (tmp_path / ".env").write_text(
        "INSTAGRAM_ACCESS_TOKEN=synthetic-dotenv-secret\n"
        "MAX_BOT_TOKEN=synthetic-dotenv-token\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "synthetic-env-secret")
    scoped = (
        "postgresql+psycopg://x@db_test/ugc_test?options="
        "-csearch_path%3Dfinancial_test_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa%2Cpublic"
    )
    config = build_test_config(scoped)
    assert config.db.database_url == scoped
    assert config.bot.bot_token == "test-token"
    assert config.instagram.instagram_access_token == ""
    assert config.instagram.scrapecreators_api_key == ""
    assert config.max_bot is None
    assert tmp_path == Path.cwd()
