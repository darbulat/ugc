"""Fresh metric provenance, bounded HTTP and conservative scheduled batches."""

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from ugc_bot import instagram_discovery_scheduler as scheduler
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.domain.instagram_discovery import (
    DiscoveryResult,
    discovery_window,
    freshest_count,
    next_discovery_run,
)
from ugc_bot.infrastructure.db.repositories.instagram import (
    _resolve_audience_rows,
)
from ugc_bot.infrastructure.db.repositories.instagram_discovery import (
    DiscoveryRepository,
)
from ugc_bot.infrastructure.instagram.discovery_client import (
    DiscoveryClient,
    DiscoveryCredential,
)
from ugc_bot.instagram_discovery_scheduler import scheduled_batch

NOW = datetime(2026, 11, 20, 8, tzinfo=timezone.utc)


def test_reader_settings_reach_repository():
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "DATABASE_URL": "sqlite:///:memory:",
            "INSTAGRAM_DISCOVERY_METRICS_ENABLED": True,
            "INSTAGRAM_IDENTITY_CONTEXT": "verified-context",
        }
    )
    reader = Container(config).build_repos()["instagram_stats_repo"]
    assert reader.include_discovery_metrics is True
    assert reader.identity_context == "verified-context"


def credential(**changes):
    return DiscoveryCredential.model_validate(
        dict(
            app_id="1528779102424926",
            business_id="17841436959803981",
            token="test-secret",
            expires_at=datetime.now(timezone.utc) + timedelta(days=60),
            expiry_fingerprint=hashlib.sha256(b"test-secret").hexdigest(),
            **changes,
        )
    )


def test_matching_uses_actual_observation_not_last_attempt():
    owner = uuid4()
    row = dict(
        user_id=owner,
        stats_id=owner,
        old_followers=9000,
        old_media=200,
        old_handle="creator",
        handle="creator",
        metrics_observed_at=None,
        identity_since=None,
        meta_followers=110,
        meta_at=NOW,
        discovery_followers=100,
        followers_observed_at=NOW - timedelta(days=1),
        discovery_media=220,
        media_observed_at=NOW,
    )
    counts = _resolve_audience_rows([row])[owner]
    assert (counts.followers_count, counts.media_count) == (110, 220)
    undated = dict(row, meta_at=None, discovery_followers=None)
    assert _resolve_audience_rows([undated])[owner].followers_count == 9000
    row["metrics_observed_at"] = NOW + timedelta(seconds=1)
    assert _resolve_audience_rows([row])[owner].followers_count == 9000
    row.update(identity_since=NOW + timedelta(days=1), old_handle="old")
    assert _resolve_audience_rows([row]) == {}


def test_counts_preserve_zero_and_unknown():
    assert freshest_count((100, None, 1), (0, NOW, 2)) == 0
    assert freshest_count((True, NOW, 2), (None, NOW, 1)) is None


def test_schedule_waits_for_future_slot_and_stops_outside_window():
    assert next_discovery_run(NOW) == datetime(
        2026, 11, 21, 7, 30, tzinfo=timezone.utc
    )
    assert next_discovery_run(NOW.replace(hour=6)).day == 20
    assert discovery_window(NOW)
    assert not discovery_window(NOW.replace(hour=11))  # 14:00 Moscow


@pytest.mark.asyncio
async def test_discovery_header_secret_and_partial_fields():
    calls = []

    def handler(request):
        calls.append(request)
        assert "test-secret" not in str(request.url)
        assert request.headers["authorization"] == "Bearer test-secret"
        assert request.url.host == "graph.facebook.com"
        return httpx.Response(
            200,
            json={
                "business_discovery": {
                    "id": "987",
                    "username": "creator",
                    "followers_count": 0,
                    "media_count": None,
                    "name": "Name",
                    "follows_count": 32,
                }
            },
            headers={"x-app-usage": '{"call_count": 51}'},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as http:
        client = DiscoveryClient(http, credential())
        result = await client.fetch("creator")
        assert result.outcome == "success"
        assert result.profile.followers_count == 0
        assert result.profile.media_count is None
        assert result.profile.details == {"name": "Name", "follows_count": 32}
        assert result.usage_percent == 51
        assert (await client.fetch("x){id}")).outcome == "invalid_handle"
        assert len(calls) == 1


@pytest.mark.parametrize(
    "error,outcome",
    [
        ({"code": 100, "error_subcode": 33}, "unavailable"),
        ({"code": 190}, "credentials"),
        ({"code": 4}, "rate_limit"),
        ({"code": 100}, "invalid_request"),
    ],
)
@pytest.mark.asyncio
async def test_provider_errors_are_not_retried(error, outcome):
    handler = AsyncMock(return_value=httpx.Response(400, json={"error": error}))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as http:
        result = await DiscoveryClient(http, credential()).fetch("creator")
    assert result.outcome == outcome
    assert handler.call_count == 1


@pytest.mark.parametrize(
    "body",
    [
        {"business_discovery": {"id": "invalid", "username": "creator"}},
        {"business_discovery": {"id": "123", "username": "bad handle"}},
        ["unexpected", "response"],
    ],
)
@pytest.mark.asyncio
async def test_malformed_profiles_do_not_become_metric_evidence(body):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=body)
        )
    ) as http:
        result = await DiscoveryClient(http, credential()).fetch("creator")
    assert result.outcome == "provider_error"
    assert result.profile is None


@pytest.mark.parametrize(
    "header,usage",
    [
        ('{"business":[{"call_count":12,"total_time":20}]}', 20),
        ('{"business":[{"call_count":"invalid"}]}', 100),
        ('{"business":[{"call_count":NaN}]}', 100),
        ("malformed-json", 100),
    ],
)
@pytest.mark.asyncio
async def test_nested_and_malformed_quota_headers_are_conservative(
    header, usage
):
    def handler(request):
        return httpx.Response(
            200,
            json={"business_discovery": {"id": "123", "username": "creator"}},
            headers={"x-business-use-case-usage": header},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as http:
        result = await DiscoveryClient(http, credential()).fetch("creator")
    assert result.usage_percent == usage


@pytest.mark.asyncio
async def test_expired_credentials_never_make_requests():
    handler = AsyncMock()
    expired = credential().model_copy(
        update={"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as http:
        result = await DiscoveryClient(http, expired).fetch("creator")
    assert result.outcome == "credentials"
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_broken_json_pauses_without_retry_or_retaining_response():
    handler = AsyncMock(
        return_value=httpx.Response(503, text="upstream unavailable")
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as http:
        result = await DiscoveryClient(http, credential()).fetch("creator")
    assert result.outcome == "network"
    assert result.profile is None
    assert handler.call_count == 1


def test_enrichment_requires_explicit_verification_context():
    with pytest.raises(ValueError, match="identity context"):
        DiscoveryRepository(None, " ")


def test_credential_requires_exact_expiry_binding_and_private_file(tmp_path):
    path = tmp_path / "credential.json"
    path.write_text(
        credential().model_dump_json().replace('"**********"', '"test-secret"')
    )
    path.chmod(0o600)
    assert DiscoveryCredential.load(path).app_id == "1528779102424926"
    data = json.loads(path.read_text())
    data["token"] = "another"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="expiry"):
        DiscoveryCredential.load(path)
    path.chmod(0o644)
    with pytest.raises(ValueError, match="owner-only"):
        DiscoveryCredential.load(path)


@pytest.mark.parametrize(
    "outcome,usage,expected",
    [("success", 0, 150), ("rate_limit", 0, 1), ("success", 50, 1)],
)
@pytest.mark.asyncio
async def test_batch_hard_cap_spacing_and_global_stop(outcome, usage, expected):
    target = SimpleNamespace(username="creator")
    repo = SimpleNamespace(
        prepare=AsyncMock(return_value=target),
        finish=AsyncMock(return_value=outcome),
        release=AsyncMock(),
    )
    client = SimpleNamespace(
        credential=credential(),
        fetch=AsyncMock(
            return_value=DiscoveryResult(outcome, usage_percent=usage)
        ),
    )
    sleep = AsyncMock()
    lease = uuid4()
    await scheduled_batch(repo, lease, client, now=lambda: NOW, sleep=sleep)
    assert client.fetch.call_count == expected
    assert all(call.args == (60,) for call in sleep.call_args_list)
    repo.release.assert_awaited_once_with(lease, outcome)


@pytest.mark.asyncio
async def test_global_error_stops_even_if_ownership_changed_during_request():
    repo = SimpleNamespace(
        prepare=AsyncMock(return_value=SimpleNamespace(username="creator")),
        finish=AsyncMock(return_value="identity_changed"),
        release=AsyncMock(),
    )
    client = SimpleNamespace(
        credential=credential(),
        fetch=AsyncMock(return_value=DiscoveryResult("credentials")),
    )
    await scheduled_batch(
        repo, uuid4(), client, now=lambda: NOW, sleep=AsyncMock()
    )
    assert client.fetch.call_count == 1


@pytest.mark.asyncio
async def test_runtime_reloads_credentials_and_does_not_log_secrets(
    monkeypatch, tmp_path, caplog
):
    real_path = type(tmp_path)
    monkeypatch.setattr(
        scheduler,
        "Path",
        lambda value: (
            tmp_path / "heartbeat"
            if value == "/tmp/discovery-heartbeat"
            else real_path(value)
        ),
    )
    monkeypatch.setenv("DATABASE_URL", "not-used")
    monkeypatch.setenv("INSTAGRAM_IDENTITY_CONTEXT", "test-context")
    repo = SimpleNamespace(claim=AsyncMock(side_effect=[None, uuid4()]))
    sessions = object()
    monkeypatch.setattr(
        scheduler, "create_session_factory", lambda value: sessions
    )
    monkeypatch.setattr(
        scheduler, "DiscoveryRepository", lambda factory, context: repo
    )
    calls = []

    def load_credential(path):
        calls.append(path)
        if len(calls) == 1:
            raise ValueError("test-secret")
        return credential()

    monkeypatch.setattr(scheduler.DiscoveryCredential, "load", load_credential)
    batch = AsyncMock(return_value="success")
    monkeypatch.setattr(scheduler, "scheduled_batch", batch)
    sleeps = 0

    async def sleep(seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps == 3:
            raise asyncio.CancelledError()

    monkeypatch.setattr(scheduler.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await scheduler.run()
    assert len(calls) == 3
    assert repo.claim.call_count == 2
    assert batch.call_count == 1
    assert "test-secret" not in caplog.text
    assert "ValueError" in caplog.text
    assert (tmp_path / "heartbeat").exists()
