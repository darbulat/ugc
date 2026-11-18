"""Expiry thresholds, credential binding and isolated admin delivery."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from pydantic import ValidationError

from ugc_bot.meta_token_monitor import (
    MonitorSettings,
    MonitorState,
    Observation,
    TokenSpec,
    _timestamp,
    alert_kind,
    health_check,
    inspect_token,
    message_text,
    run_once,
    send_alert,
)

NOW = datetime(2026, 11, 18, 13, tzinfo=timezone.utc)
ADMINS = ["101", "202", "303"]


def token_spec(key="verification", *, expiry=NOW + timedelta(days=30)):
    secret = "instagram-secret" if key == "verification" else "facebook-secret"
    return TokenSpec(
        key=key,
        purpose="Рабочая верификация"
        if key == "verification"
        else "Статистика",
        kind="instagram_login" if key == "verification" else "facebook_user",
        token=secret,
        app_id="pilot-app" if key == "discovery" else "",
        required_scopes=["instagram_basic"] if key == "discovery" else [],
        expires_at=expiry,
        expiry_fingerprint=hashlib.sha256(secret.encode()).hexdigest(),
    )


def settings(*, verification=None, discovery=None):
    return MonitorSettings(
        bot_token="telegram-secret",
        recipients=ADMINS,
        tokens=[
            verification or token_spec(),
            discovery or token_spec("discovery"),
        ],
    )


class Endpoints:
    def __init__(self):
        self.expiry = NOW + timedelta(days=30)
        self.telegram_requests = []
        self.meta_requests = []
        self.failed_recipient = None
        self.instagram_status = 200

    def __call__(self, request):
        if request.url.host == "api.telegram.org":
            body = json.loads(request.content)
            self.telegram_requests.append(body)
            if body["chat_id"] == self.failed_recipient:
                return httpx.Response(403, json={"ok": False})
            return httpx.Response(200, json={"ok": True, "result": {}})
        self.meta_requests.append(request)
        assert request.method == "GET"
        if request.url.host == "graph.instagram.com":
            if self.instagram_status != 200:
                return httpx.Response(self.instagram_status, json={})
            return httpx.Response(
                200, json={"username": "usemycontent", "user_id": "ig-account"}
            )
        assert request.url.host == "graph.facebook.com"
        assert request.url.path == "/v27.0/debug_token"
        return httpx.Response(
            200,
            json={
                "data": {
                    "app_id": "pilot-app",
                    "is_valid": True,
                    "scopes": ["instagram_basic"],
                    "expires_at": int(self.expiry.timestamp()),
                }
            },
        )


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (7 * 86400 + 1, None),
        (7 * 86400, "seven_days"),
        (86401, "seven_days"),
        (86400, "one_day"),
        (1, "one_day"),
        (0, "expired"),
        (-1, "expired"),
    ],
)
def test_expiry_thresholds(seconds, expected):
    observation = Observation("valid", NOW + timedelta(seconds=seconds))
    assert alert_kind(observation, NOW, 0) == expected


@pytest.mark.parametrize(
    ("health", "failures", "expected"),
    [
        ("valid", 0, "expiry_unknown"),
        ("invalid", 0, "invalid"),
        ("missing", 0, "missing"),
        ("unavailable", 1, None),
        ("unavailable", 2, None),
        ("unavailable", 3, "check_unavailable"),
    ],
)
def test_unknown_and_unavailable_are_not_expired(health, failures, expected):
    assert alert_kind(Observation(health, None), NOW, failures) == expected


def test_settings_limit_delivery_to_explicit_private_admins():
    for recipients in (
        [],
        ["1", "2", "3", "4"],
        ["1", "1", "2"],
        ["1", "2", "-100"],
    ):
        with pytest.raises(ValidationError):
            MonitorSettings(
                bot_token="secret",
                recipients=recipients,
                tokens=settings().tokens,
            )
    with pytest.raises(ValidationError):
        MonitorSettings(
            bot_token="secret", recipients=ADMINS, tokens=[token_spec()]
        )


def test_expiry_is_bound_to_exact_token():
    spec = token_spec()
    assert spec.recorded_expiry is not None
    changed = spec.model_copy(update={"expiry_fingerprint": "other-token"})
    assert changed.recorded_expiry is None
    assert "instagram-secret" not in repr(spec)
    assert "telegram-secret" not in repr(settings())


@pytest.mark.parametrize("value", [None, 0, -1, True, "123", 10**40])
def test_invalid_expiry_metadata_is_not_a_calendar_date(value):
    assert _timestamp(value) is None


def test_facebook_uses_earliest_positive_expiry_and_required_permissions():
    def endpoint(request):
        assert request.headers["Authorization"] == "Bearer facebook-secret"
        return httpx.Response(
            200,
            json={
                "data": {
                    "app_id": "pilot-app",
                    "is_valid": True,
                    "scopes": ["instagram_basic"],
                    "expires_at": int((NOW + timedelta(days=60)).timestamp()),
                    "data_access_expires_at": int(
                        (NOW + timedelta(days=5)).timestamp()
                    ),
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(endpoint)) as client:
        observed = inspect_token(client, token_spec("discovery"))
    assert observed == Observation("valid", NOW + timedelta(days=5))


@pytest.mark.parametrize(
    "data",
    [
        {"app_id": "other", "is_valid": True, "scopes": ["instagram_basic"]},
        {"app_id": "pilot-app", "is_valid": False, "scopes": []},
        {"app_id": "pilot-app", "is_valid": True, "scopes": []},
        {"app_id": "pilot-app", "is_valid": True, "scopes": None},
    ],
)
def test_wrong_app_or_permissions_raise_access_alert(data):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"data": data})
        )
    ) as client:
        assert (
            inspect_token(client, token_spec("discovery")).health == "invalid"
        )


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (400, {"error": {"code": 190}}, "invalid"),
        (403, {"error": {"code": 10}}, "invalid"),
        (403, {"error": {"code": 200}}, "invalid"),
        (429, {"error": {"code": 4}}, "unavailable"),
        (500, {}, "unavailable"),
        (200, [], "unavailable"),
        (200, {"data": []}, "unavailable"),
    ],
)
def test_api_errors_have_distinct_monitoring_meanings(status, body, expected):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, json=body)
        )
    ) as client:
        assert inspect_token(client, token_spec("discovery")).health == expected


def test_instagram_does_not_guess_expiry_or_refresh_credentials():
    endpoint = Endpoints()
    with httpx.Client(transport=httpx.MockTransport(endpoint)) as client:
        observed = inspect_token(client, token_spec(expiry=None))
    assert observed == Observation("valid", None)
    assert len(endpoint.meta_requests) == 1
    assert endpoint.meta_requests[0].url.path == "/v24.0/me"


def test_account_mismatch_and_missing_token_are_not_healthy():
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"username": "different"})
        )
    ) as client:
        assert inspect_token(client, token_spec()).health == "invalid"
        empty = TokenSpec(
            key="verification", purpose="Working", kind="instagram_login"
        )
        assert inspect_token(client, empty) == Observation("missing", None)


@pytest.mark.parametrize("malformed", [True, False])
def test_network_or_non_json_response_retains_known_deadline(malformed):
    def endpoint(request):
        if malformed:
            return httpx.Response(200, text="not json")
        raise httpx.ConnectError(
            "sensitive URL must not be logged", request=request
        )

    with httpx.Client(transport=httpx.MockTransport(endpoint)) as client:
        observed = inspect_token(client, token_spec())
    assert observed == Observation("unavailable", NOW + timedelta(days=30))


def test_no_expiry_metadata_can_use_a_bound_cached_deadline():
    def endpoint(request):
        return httpx.Response(
            200,
            json={
                "data": {
                    "is_valid": True,
                    "app_id": "pilot-app",
                    "scopes": ["instagram_basic"],
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(endpoint)) as client:
        assert inspect_token(
            client, token_spec("discovery")
        ).expires_at == NOW + timedelta(days=30)


def test_failed_recipient_retries_without_resending_to_others(tmp_path):
    endpoint = Endpoints()
    endpoint.failed_recipient = "202"
    config = settings(verification=token_spec(expiry=NOW + timedelta(days=7)))
    state = MonitorState(tmp_path / "state.sqlite3")
    with httpx.Client(transport=httpx.MockTransport(endpoint)) as client:
        first = run_once(config, state, client, NOW)
        assert first["tokens"][0]["sent"] == 2
        assert first["tokens"][0]["delivery_errors"] == 1
        endpoint.failed_recipient = None
        second = run_once(config, state, client, NOW + timedelta(hours=1))
        assert second["tokens"][0]["sent"] == 1
    assert [r["chat_id"] for r in endpoint.telegram_requests] == ADMINS + [
        "202"
    ]
    state.close()


def test_removed_recipient_is_excluded_from_retries_and_new_alerts(tmp_path):
    endpoint = Endpoints()
    endpoint.failed_recipient = "303"
    config = settings(verification=token_spec(expiry=NOW + timedelta(days=7)))
    state = MonitorState(tmp_path / "state.sqlite3")
    with httpx.Client(transport=httpx.MockTransport(endpoint)) as client:
        first = run_once(config, state, client, NOW)
        assert first["tokens"][0]["delivery_errors"] == 1
        config.recipients = ["101", "202"]
        endpoint.failed_recipient = None
        endpoint.telegram_requests.clear()
        run_once(config, state, client, NOW + timedelta(hours=1))
        assert not endpoint.telegram_requests
        config.tokens[0].expires_at = NOW + timedelta(days=13)
        result = run_once(config, state, client, NOW + timedelta(days=6))
    assert result["tokens"][0]["sent"] == 2
    assert [item["chat_id"] for item in endpoint.telegram_requests] == [
        "101",
        "202",
    ]
    state.close()


def test_restart_one_day_threshold_and_new_expiry_cycle(tmp_path):
    path = tmp_path / "state.sqlite3"
    config = settings(verification=token_spec(expiry=NOW + timedelta(days=7)))
    endpoint = Endpoints()
    with httpx.Client(transport=httpx.MockTransport(endpoint)) as client:
        state = MonitorState(path)
        run_once(config, state, client, NOW)
        state.close()
        state = MonitorState(path)
        assert run_once(config, state, client, NOW)["tokens"][0]["sent"] == 0
        later = NOW + timedelta(days=6)
        assert run_once(config, state, client, later)["tokens"][0]["sent"] == 3
        config.tokens[0].expires_at += timedelta(days=60)
        assert run_once(config, state, client, later)["tokens"][0]["sent"] == 0
        newest = later + timedelta(days=60)
        assert run_once(config, state, client, newest)["tokens"][0]["sent"] == 3
        state.close()


def test_late_start_sends_only_urgent_threshold_and_dry_run_does_not_send(
    tmp_path,
):
    endpoint = Endpoints()
    config = settings(verification=token_spec(expiry=NOW + timedelta(hours=4)))
    state = MonitorState(tmp_path / "state.sqlite3")
    with httpx.Client(transport=httpx.MockTransport(endpoint)) as client:
        dry = run_once(config, state, client, NOW, dry_run=True)
        assert dry["tokens"][0]["alert"] == "one_day"
        assert not endpoint.telegram_requests
        assert state.read("heartbeat") == {}
        actual = run_once(config, state, client, NOW)
    assert actual["tokens"][0]["sent"] == 3
    assert len(endpoint.telegram_requests) == 3
    state.close()


def test_unavailable_requires_three_attempts_and_recovers(tmp_path):
    endpoint = Endpoints()
    endpoint.instagram_status = 503
    config = settings()
    state = MonitorState(tmp_path / "state.sqlite3")
    with httpx.Client(transport=httpx.MockTransport(endpoint)) as client:
        for attempt in range(3):
            result = run_once(
                config, state, client, NOW + timedelta(hours=attempt)
            )
        assert result["tokens"][0]["alert"] == "check_unavailable"
        assert len(endpoint.telegram_requests) == 3
        endpoint.instagram_status = 200
        assert (
            run_once(config, state, client, NOW)["tokens"][0]["alert"] is None
        )
    state.close()


def test_cache_is_not_reused_for_a_changed_credential(tmp_path):
    endpoint = Endpoints()
    config = settings()
    state = MonitorState(tmp_path / "state.sqlite3")
    with httpx.Client(transport=httpx.MockTransport(endpoint)) as client:
        run_once(config, state, client, NOW)
        config.tokens[0] = token_spec(expiry=None).model_copy(
            update={"expiry_fingerprint": "not-the-token"}
        )
        assert (
            run_once(config, state, client, NOW)["tokens"][0]["expires_at"]
            is not None
        )
        config.tokens[0] = TokenSpec(
            key="verification",
            purpose="New",
            kind="instagram_login",
            token="different-secret",
        )
        result = run_once(config, state, client, NOW)
    assert result["tokens"][0]["alert"] == "expiry_unknown"
    assert result["tokens"][0]["expires_at"] is None
    state.close()


def test_health_and_messages_contain_no_secrets(tmp_path):
    path = tmp_path / "state.sqlite3"
    assert not health_check(path, NOW)
    state = MonitorState(path)
    assert not health_check(path, NOW)
    state.write("heartbeat", {"checked_at": NOW.isoformat()})
    assert health_check(path, NOW + timedelta(hours=1))
    assert not health_check(path, NOW + timedelta(hours=3))
    assert not health_check(path, NOW - timedelta(seconds=1))
    spec = token_spec("discovery")
    text = message_text(spec, Observation("valid", NOW), "one_day")
    assert "18.11.2026 16:00 МСК" in text
    assert "отдельный доступ к статистике" in text
    assert "facebook-secret" not in text
    assert not any(
        secret in path.read_bytes().decode(errors="ignore")
        for secret in ["instagram-secret", "facebook-secret", "telegram-secret"]
    )
    state.close()


@pytest.mark.parametrize("body", [{"ok": False}, [], {"ok": True}])
def test_telegram_success_requires_confirmed_response(body):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=body)
        )
    ) as client:
        assert send_alert(client, settings().bot_token, "101", "message") is (
            body == {"ok": True}
        )


def test_telegram_network_failure_and_bad_json_are_retryable():
    for malformed in [True, False]:

        def endpoint(request, malformed=malformed):
            if malformed:
                return httpx.Response(200, text="bad json")
            raise httpx.ConnectError("secret", request=request)

        with httpx.Client(transport=httpx.MockTransport(endpoint)) as client:
            assert not send_alert(
                client, settings().bot_token, "101", "message"
            )
