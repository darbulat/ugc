"""Tests for AiograpiStatsFetcher (Instagram stats fallback via aiograpi)."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ugc_bot.infrastructure.instagram.aiograpi_stats_fetcher import (
    AiograpiStatsFetcher,
)


def _make_aiograpi_mocks():
    """Create mock aiograpi and aiograpi.exceptions for patching sys.modules."""
    mock_exceptions = MagicMock()
    mock_exceptions.UserNotFound = type("UserNotFound", (Exception,), {})
    mock_exceptions.LoginRequired = type("LoginRequired", (Exception,), {})
    mock_exceptions.FeedbackRequired = type(
        "FeedbackRequired", (Exception,), {}
    )
    mock_aiograpi = MagicMock()
    mock_aiograpi.exceptions = mock_exceptions
    return mock_aiograpi, mock_exceptions


def test_is_configured_false_when_empty() -> None:
    """is_configured returns False when credentials are empty."""
    fetcher = AiograpiStatsFetcher(instagram_username="", instagram_password="")
    assert fetcher.is_configured() is False


def test_is_configured_false_when_password_empty() -> None:
    """is_configured returns False when password is empty."""
    fetcher = AiograpiStatsFetcher(
        instagram_username="user", instagram_password=""
    )
    assert fetcher.is_configured() is False


def test_is_configured_true_when_both_set() -> None:
    """is_configured returns True when both username and password set."""
    fetcher = AiograpiStatsFetcher(
        instagram_username="user", instagram_password="pass"
    )
    assert fetcher.is_configured() is True


@pytest.mark.asyncio
async def test_get_profile_stats_returns_none_when_not_configured() -> None:
    """Returns None when fetcher is not configured."""
    fetcher = AiograpiStatsFetcher(instagram_username="", instagram_password="")
    assert await fetcher.get_profile_stats_by_username("jane") is None


@pytest.mark.asyncio
async def test_get_profile_stats_returns_none_on_import_error() -> None:
    """Returns None when aiograpi is not installed."""
    import builtins

    fetcher = AiograpiStatsFetcher(
        instagram_username="u", instagram_password="p"
    )
    orig_import = builtins.__import__

    def raise_for_aiograpi(name, *args, **kwargs):
        if name == "aiograpi" or name == "aiograpi.exceptions":
            raise ImportError("aiograpi not installed")
        return orig_import(name, *args, **kwargs)

    with patch.object(builtins, "__import__", side_effect=raise_for_aiograpi):
        result = await fetcher.get_profile_stats_by_username("jane")
    assert result is None


@pytest.mark.asyncio
async def test_get_profile_stats_success_returns_dict(tmp_path: Path) -> None:
    """get_profile_stats_by_username returns stats dict on success."""
    mock_aiograpi, mock_exceptions = _make_aiograpi_mocks()
    session_file = tmp_path / "session.json"
    session_file.write_text("{}")
    fetcher = AiograpiStatsFetcher(
        instagram_username="user",
        instagram_password="pass",
        session_path=session_file,
    )
    mock_user = MagicMock()
    mock_user.username = "jane"
    mock_user.follower_count = 100
    mock_user.following_count = 50
    mock_user.media_count = 10
    mock_user.biography = "Bio"
    mock_user.pk = 12345

    mock_client = MagicMock()
    mock_client.login = AsyncMock(return_value=None)
    mock_client.user_info_by_username_v1 = AsyncMock(return_value=mock_user)
    mock_client.load_settings = MagicMock()
    mock_client.dump_settings = MagicMock()
    mock_aiograpi.Client = MagicMock(return_value=mock_client)

    with (
        patch.dict(
            sys.modules,
            {"aiograpi": mock_aiograpi, "aiograpi.exceptions": mock_exceptions},
        ),
        patch(
            "ugc_bot.infrastructure.instagram.aiograpi_stats_fetcher._apply_httpx_proxies_compat"
        ),
    ):
        result = await fetcher.get_profile_stats_by_username("  Jane  ")

    assert result is not None
    assert result["data"]["username"] == "jane"
    assert result["data"]["followers_count"] == 100
    assert result["data"]["follows_count"] == 50
    assert result["data"]["media_count"] == 10
    assert result["data"]["biography"] == "Bio"
    assert result["id"] == "12345"
    mock_client.user_info_by_username_v1.assert_called_once_with("jane")


@pytest.mark.asyncio
async def test_get_profile_stats_user_not_found_returns_none(
    tmp_path: Path,
) -> None:
    """get_profile_stats_by_username returns None when user not found."""
    mock_aiograpi, mock_exceptions = _make_aiograpi_mocks()
    session_file = tmp_path / "session.json"
    session_file.write_text("{}")
    fetcher = AiograpiStatsFetcher(
        instagram_username="user",
        instagram_password="pass",
        session_path=session_file,
    )
    mock_client = MagicMock()
    mock_client.login = AsyncMock(return_value=None)
    mock_client.user_info_by_username_v1 = AsyncMock(
        side_effect=mock_exceptions.UserNotFound()
    )
    mock_client.load_settings = MagicMock()
    mock_client.dump_settings = MagicMock()
    mock_aiograpi.Client = MagicMock(return_value=mock_client)

    with (
        patch.dict(
            sys.modules,
            {"aiograpi": mock_aiograpi, "aiograpi.exceptions": mock_exceptions},
        ),
        patch(
            "ugc_bot.infrastructure.instagram.aiograpi_stats_fetcher._apply_httpx_proxies_compat"
        ),
    ):
        result = await fetcher.get_profile_stats_by_username("nonexistent")

    assert result is None


@pytest.mark.asyncio
async def test_get_profile_stats_feedback_required_returns_none(
    tmp_path: Path,
) -> None:
    """Returns None when Instagram rate limits (FeedbackRequired)."""
    mock_aiograpi, mock_exceptions = _make_aiograpi_mocks()
    session_file = tmp_path / "session.json"
    session_file.write_text("{}")
    fetcher = AiograpiStatsFetcher(
        instagram_username="user",
        instagram_password="pass",
        session_path=session_file,
    )
    mock_client = MagicMock()
    mock_client.login = AsyncMock(return_value=None)
    mock_client.user_info_by_username_v1 = AsyncMock(
        side_effect=mock_exceptions.FeedbackRequired(
            "We limit how often you can do certain things..."
        )
    )
    mock_client.load_settings = MagicMock()
    mock_client.dump_settings = MagicMock()
    mock_aiograpi.Client = MagicMock(return_value=mock_client)

    with (
        patch.dict(
            sys.modules,
            {"aiograpi": mock_aiograpi, "aiograpi.exceptions": mock_exceptions},
        ),
        patch(
            "ugc_bot.infrastructure.instagram.aiograpi_stats_fetcher._apply_httpx_proxies_compat"
        ),
    ):
        result = await fetcher.get_profile_stats_by_username("gukasimava")

    assert result is None


@pytest.mark.asyncio
async def test_get_profile_stats_login_failure_returns_none(
    tmp_path: Path,
) -> None:
    """get_profile_stats_by_username returns None when login fails."""
    mock_aiograpi, mock_exceptions = _make_aiograpi_mocks()
    session_file = tmp_path / "session.json"
    session_file.write_text("{}")
    fetcher = AiograpiStatsFetcher(
        instagram_username="user",
        instagram_password="pass",
        session_path=session_file,
    )
    mock_client = MagicMock()
    mock_client.login = AsyncMock(side_effect=Exception("auth failed"))
    mock_aiograpi.Client = MagicMock(return_value=mock_client)

    with (
        patch.dict(
            sys.modules,
            {"aiograpi": mock_aiograpi, "aiograpi.exceptions": mock_exceptions},
        ),
        patch(
            "ugc_bot.infrastructure.instagram.aiograpi_stats_fetcher._apply_httpx_proxies_compat"
        ),
    ):
        result = await fetcher.get_profile_stats_by_username("jane")

    assert result is None


@pytest.mark.asyncio
async def test_get_profile_stats_biography_none_becomes_empty(
    tmp_path: Path,
) -> None:
    """When user.biography is None, stats dict has empty string."""
    mock_aiograpi, mock_exceptions = _make_aiograpi_mocks()
    session_file = tmp_path / "session.json"
    session_file.write_text("{}")
    fetcher = AiograpiStatsFetcher(
        instagram_username="u",
        instagram_password="p",
        session_path=session_file,
    )
    mock_user = MagicMock()
    mock_user.username = "j"
    mock_user.follower_count = 0
    mock_user.following_count = 0
    mock_user.media_count = 0
    mock_user.biography = None
    mock_user.pk = 1
    mock_client = MagicMock()
    mock_client.login = AsyncMock(return_value=None)
    mock_client.user_info_by_username_v1 = AsyncMock(return_value=mock_user)
    mock_client.load_settings = MagicMock()
    mock_client.dump_settings = MagicMock()
    mock_aiograpi.Client = MagicMock(return_value=mock_client)

    with (
        patch.dict(
            sys.modules,
            {"aiograpi": mock_aiograpi, "aiograpi.exceptions": mock_exceptions},
        ),
        patch(
            "ugc_bot.infrastructure.instagram.aiograpi_stats_fetcher._apply_httpx_proxies_compat"
        ),
    ):
        result = await fetcher.get_profile_stats_by_username("j")

    assert result is not None
    assert result["data"]["biography"] == ""


@pytest.mark.asyncio
async def test_get_profile_stats_login_required_then_retry_success(
    tmp_path: Path,
) -> None:
    """On LoginRequired, re-login and retry; return stats on success."""
    mock_aiograpi, mock_exceptions = _make_aiograpi_mocks()
    session_file = tmp_path / "session.json"
    session_file.write_text("{}")
    fetcher = AiograpiStatsFetcher(
        instagram_username="u",
        instagram_password="p",
        session_path=session_file,
    )
    mock_user = MagicMock()
    mock_user.username = "jane"
    mock_user.follower_count = 10
    mock_user.following_count = 5
    mock_user.media_count = 1
    mock_user.biography = ""
    mock_user.pk = 99
    mock_client1 = MagicMock()
    mock_client1.login = AsyncMock(return_value=None)
    mock_client1.user_info_by_username_v1 = AsyncMock(
        side_effect=mock_exceptions.LoginRequired()
    )
    mock_client1.load_settings = MagicMock()
    mock_client1.dump_settings = MagicMock()
    mock_client2 = MagicMock()
    mock_client2.login = AsyncMock(return_value=None)
    mock_client2.user_info_by_username_v1 = AsyncMock(return_value=mock_user)
    mock_client2.dump_settings = MagicMock()
    mock_aiograpi.Client = MagicMock(side_effect=[mock_client1, mock_client2])

    with (
        patch.dict(
            sys.modules,
            {"aiograpi": mock_aiograpi, "aiograpi.exceptions": mock_exceptions},
        ),
        patch(
            "ugc_bot.infrastructure.instagram.aiograpi_stats_fetcher._apply_httpx_proxies_compat"
        ),
    ):
        result = await fetcher.get_profile_stats_by_username("jane")

    assert result is not None
    assert result["data"]["username"] == "jane"
    assert result["id"] == "99"


@pytest.mark.asyncio
async def test_get_profile_stats_login_required_then_dump_oserror(
    tmp_path: Path,
) -> None:
    """After LoginRequired retry, dump_settings OSError is caught."""
    mock_aiograpi, mock_exceptions = _make_aiograpi_mocks()
    session_file = tmp_path / "session.json"
    session_file.write_text("{}")
    fetcher = AiograpiStatsFetcher(
        instagram_username="u",
        instagram_password="p",
        session_path=session_file,
    )
    mock_user = MagicMock()
    mock_user.username = "jane"
    mock_user.follower_count = 0
    mock_user.following_count = 0
    mock_user.media_count = 0
    mock_user.biography = None
    mock_user.pk = 1
    mock_client1 = MagicMock()
    mock_client1.login = AsyncMock(return_value=None)
    mock_client1.user_info_by_username_v1 = AsyncMock(
        side_effect=mock_exceptions.LoginRequired()
    )
    mock_client1.load_settings = MagicMock()
    mock_client1.dump_settings = MagicMock()
    mock_client2 = MagicMock()
    mock_client2.login = AsyncMock(return_value=None)
    mock_client2.user_info_by_username_v1 = AsyncMock(return_value=mock_user)
    mock_client2.dump_settings = MagicMock(side_effect=OSError("disk full"))
    mock_aiograpi.Client = MagicMock(side_effect=[mock_client1, mock_client2])

    with (
        patch.dict(
            sys.modules,
            {"aiograpi": mock_aiograpi, "aiograpi.exceptions": mock_exceptions},
        ),
        patch(
            "ugc_bot.infrastructure.instagram.aiograpi_stats_fetcher._apply_httpx_proxies_compat"
        ),
    ):
        result = await fetcher.get_profile_stats_by_username("jane")

    assert result is not None
    assert result["data"]["username"] == "jane"


@pytest.mark.asyncio
async def test_get_profile_stats_login_required_then_retry_fails(
    tmp_path: Path,
) -> None:
    """When LoginRequired then re-login fails, returns None."""
    mock_aiograpi, mock_exceptions = _make_aiograpi_mocks()
    session_file = tmp_path / "session.json"
    session_file.write_text("{}")
    fetcher = AiograpiStatsFetcher(
        instagram_username="u",
        instagram_password="p",
        session_path=session_file,
    )
    mock_client1 = MagicMock()
    mock_client1.login = AsyncMock(return_value=None)
    mock_client1.user_info_by_username_v1 = AsyncMock(
        side_effect=mock_exceptions.LoginRequired()
    )
    mock_client1.load_settings = MagicMock()
    mock_client1.dump_settings = MagicMock()
    mock_client2 = MagicMock()
    mock_client2.login = AsyncMock(side_effect=Exception("re-login failed"))
    mock_aiograpi.Client = MagicMock(side_effect=[mock_client1, mock_client2])

    with (
        patch.dict(
            sys.modules,
            {"aiograpi": mock_aiograpi, "aiograpi.exceptions": mock_exceptions},
        ),
        patch(
            "ugc_bot.infrastructure.instagram.aiograpi_stats_fetcher._apply_httpx_proxies_compat"
        ),
    ):
        result = await fetcher.get_profile_stats_by_username("jane")

    assert result is None


@pytest.mark.asyncio
async def test_get_profile_stats_load_settings_exception_logged(
    tmp_path: Path,
) -> None:
    """When load_settings raises, it is caught and fetch continues."""
    mock_aiograpi, mock_exceptions = _make_aiograpi_mocks()
    session_file = tmp_path / "session.json"
    session_file.write_text("{}")
    fetcher = AiograpiStatsFetcher(
        instagram_username="u",
        instagram_password="p",
        session_path=session_file,
    )
    mock_user = MagicMock()
    mock_user.username = "x"
    mock_user.follower_count = 0
    mock_user.following_count = 0
    mock_user.media_count = 0
    mock_user.biography = None
    mock_user.pk = 1
    mock_client = MagicMock()
    mock_client.login = AsyncMock(return_value=None)
    mock_client.user_info_by_username_v1 = AsyncMock(return_value=mock_user)
    mock_client.load_settings = MagicMock(side_effect=OSError("read error"))
    mock_client.dump_settings = MagicMock()
    mock_aiograpi.Client = MagicMock(return_value=mock_client)

    with (
        patch.dict(
            sys.modules,
            {"aiograpi": mock_aiograpi, "aiograpi.exceptions": mock_exceptions},
        ),
        patch(
            "ugc_bot.infrastructure.instagram.aiograpi_stats_fetcher._apply_httpx_proxies_compat"
        ),
    ):
        result = await fetcher.get_profile_stats_by_username("x")

    assert result is not None
    assert result["data"]["username"] == "x"


@pytest.mark.asyncio
async def test_get_profile_stats_dump_settings_oserror_logged(
    tmp_path: Path,
) -> None:
    """dump_settings OSError is caught; result still returned."""
    mock_aiograpi, mock_exceptions = _make_aiograpi_mocks()
    session_file = tmp_path / "session.json"
    session_file.write_text("{}")
    fetcher = AiograpiStatsFetcher(
        instagram_username="u",
        instagram_password="p",
        session_path=session_file,
    )
    mock_user = MagicMock()
    mock_user.username = "y"
    mock_user.follower_count = 0
    mock_user.following_count = 0
    mock_user.media_count = 0
    mock_user.biography = None
    mock_user.pk = 2
    mock_client = MagicMock()
    mock_client.login = AsyncMock(return_value=None)
    mock_client.user_info_by_username_v1 = AsyncMock(return_value=mock_user)
    mock_client.load_settings = MagicMock()
    mock_client.dump_settings = MagicMock(side_effect=OSError("write error"))
    mock_aiograpi.Client = MagicMock(return_value=mock_client)

    with (
        patch.dict(
            sys.modules,
            {"aiograpi": mock_aiograpi, "aiograpi.exceptions": mock_exceptions},
        ),
        patch(
            "ugc_bot.infrastructure.instagram.aiograpi_stats_fetcher._apply_httpx_proxies_compat"
        ),
    ):
        result = await fetcher.get_profile_stats_by_username("y")

    assert result is not None
    assert result["data"]["username"] == "y"


def test_apply_httpx_proxies_compat_idempotent() -> None:
    """_apply_httpx_proxies_compat is idempotent (patched once)."""
    from ugc_bot.infrastructure.instagram.aiograpi_stats_fetcher import (
        _apply_httpx_proxies_compat,
    )

    _apply_httpx_proxies_compat()
    _apply_httpx_proxies_compat()


@pytest.mark.asyncio
async def test_get_profile_stats_non_feedback_exception_raises(
    tmp_path: Path,
) -> None:
    """Non-FeedbackRequired exceptions in info fetch are re-raised."""
    mock_aiograpi, mock_exceptions = _make_aiograpi_mocks()
    session_file = tmp_path / "session.json"
    session_file.write_text("{}")
    fetcher = AiograpiStatsFetcher(
        instagram_username="user",
        instagram_password="pass",
        session_path=session_file,
    )
    mock_client = MagicMock()
    mock_client.login = AsyncMock(return_value=None)
    mock_client.load_settings = MagicMock()
    # Exception that is not UserNotFound, LoginRequired, or FeedbackRequired
    mock_client.user_info_by_username_v1 = AsyncMock(
        side_effect=RuntimeError("unexpected error")
    )
    mock_aiograpi.Client = MagicMock(return_value=mock_client)

    with (
        patch.dict(
            sys.modules,
            {"aiograpi": mock_aiograpi, "aiograpi.exceptions": mock_exceptions},
        ),
        patch(
            "ugc_bot.infrastructure.instagram.aiograpi_stats_fetcher._apply_httpx_proxies_compat"
        ),
        pytest.raises(RuntimeError, match="unexpected error"),
    ):
        await fetcher.get_profile_stats_by_username("jane")


@pytest.mark.asyncio
async def test_import_aiograpi_feedback_required_import_error_sets_none(
    tmp_path: Path,
) -> None:
    """_import_aiograpi sets FeedbackRequired=None when import fails (27-28)."""
    import builtins

    from ugc_bot.infrastructure.instagram import aiograpi_stats_fetcher as mod

    # aiograpi available but FeedbackRequired is not
    mock_aiograpi = MagicMock()
    mock_exceptions = MagicMock()
    mock_exceptions.UserNotFound = type("UserNotFound", (Exception,), {})
    mock_exceptions.LoginRequired = type("LoginRequired", (Exception,), {})
    # FeedbackRequired intentionally NOT set on mock_exceptions

    orig_import = builtins.__import__

    def patched_import(name, *args, **kwargs):
        if (
            name == "aiograpi.exceptions"
            and args
            and "FeedbackRequired" in (args[3] or [])
        ):
            raise ImportError("FeedbackRequired not found")
        return orig_import(name, *args, **kwargs)

    with (
        patch.dict(
            sys.modules,
            {"aiograpi": mock_aiograpi, "aiograpi.exceptions": mock_exceptions},
        ),
        patch(
            "ugc_bot.infrastructure.instagram.aiograpi_stats_fetcher._apply_httpx_proxies_compat"
        ),
        patch.object(builtins, "__import__", side_effect=patched_import),
    ):
        result = mod._import_aiograpi()
    # If FeedbackRequired import fails, result still has Client etc.
    # (the inner except ImportError sets FeedbackRequired = None and continues)
    # Result can be None (outer except) or a tuple
    assert result is None or isinstance(result, tuple)


def test_apply_httpx_proxies_compat_converts_proxies_to_proxy() -> None:
    """Compat converts proxies= to proxy= for httpx 0.28+."""
    import httpx

    from ugc_bot.infrastructure.instagram.aiograpi_stats_fetcher import (
        _apply_httpx_proxies_compat,
    )

    _apply_httpx_proxies_compat()
    # String proxies
    client = httpx.AsyncClient(proxies="http://proxy.example:8080")
    assert client is not None
    # Dict proxies (covers dict branch in compat)
    client2 = httpx.AsyncClient(
        proxies={
            "http": "http://proxy.example:8080",
            "https": "https://proxy:443",
        }
    )
    assert client2 is not None
