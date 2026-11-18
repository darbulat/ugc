"""External monitoring behaviour, with all transports isolated from users."""

import ast
import hashlib
import json
import stat
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import boto3
import pytest

from scripts import external_monitor as monitor
from scripts import monitor_snapshot as reporter


def observation(ok=False, name="Mini App"):
    return monitor.Observation(name, ok, "Недоступно")


def test_transient_failure_and_recovery_are_silent():
    state = {}
    assert monitor.evaluate(state, [observation()], 100) == []
    assert monitor.evaluate(state, [observation(True)], 130) == []
    assert monitor.evaluate(state, [observation()], 160) == []


def test_confirmed_incident_reminder_recovery_and_restart(tmp_path):
    state = {}
    monitor.evaluate(state, [observation()], 100)
    events = monitor.evaluate(state, [observation()], 130)
    assert len(events) == 1
    # A failed/unconfirmed delivery must remain retryable.
    assert monitor.evaluate(state, [observation()], 160) == events
    monitor.acknowledge(state, events, 160)
    path = tmp_path / "state.json"
    monitor.atomic_json(path, state)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    state = monitor.load_state(path)
    assert monitor.evaluate(state, [observation()], 161) == []
    assert monitor.evaluate(state, [observation()], 160 + 14400) == events
    recovered = monitor.evaluate(state, [observation(True)], 15000)
    assert recovered[0].recovered
    assert "Недоступно" not in monitor.format_message(recovered)
    monitor.acknowledge(state, recovered, 15000)
    assert monitor.evaluate(state, [observation(True)], 15030) == []


def test_multiple_failures_are_grouped_into_one_message():
    state = {}
    values = [observation(name="Mini App"), observation(name="Админка")]
    monitor.evaluate(state, values, 100)
    events = monitor.evaluate(state, values, 130)
    message = monitor.format_message(events)
    assert message.count("UMC · внешний мониторинг") == 1
    assert "Mini App" in message and "Админка" in message
    assert len(message) < 4096


@pytest.mark.parametrize(
    "body,healthy", [(b"<title>UMC", True), (b"empty", False)]
)
def test_page_must_have_expected_content(monkeypatch, body, healthy):
    monkeypatch.setattr(monitor, "request_bytes", lambda url: body)
    result = monitor.check_page(
        {
            "name": "Mini App",
            "url": "https://example.org",
            "contains": "<title>UMC",
        }
    )
    assert result.ok is healthy


def test_transport_error_never_exposes_urls_or_credentials(monkeypatch):
    def fail(url):
        raise ValueError("private-token-in-error-https://example.org/secret")

    monkeypatch.setattr(monitor, "request_bytes", fail)
    result = monitor.check_page(
        {"name": "Mini App", "url": "https://example.org", "contains": "UMC"}
    )
    assert not result.ok
    assert "secret" not in result.detail and "token" not in result.detail


def _peer_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", "umc-monitor-snapshot")
    monkeypatch.setenv(
        "SSH_CONNECTION", "194.87.131.138 41234 31.59.106.143 22"
    )
    monkeypatch.setattr(monitor, "time", SimpleNamespace(time=lambda: 1000))
    return {"name": "peer", "type": "peer_heartbeat", "host": "194.87.131.138"}


@pytest.mark.parametrize(
    "age,expected",
    [(0, True), (90, True), (90.001, False), (-30, True), (-31, False)],
)
def test_peer_query_roundtrip_and_freshness_boundary(
    monkeypatch, tmp_path, age, expected
):
    probe = _peer_environment(monkeypatch, tmp_path)
    reporter.record_peer_query(
        {"version": 1, "generated_at": 1000 - age, "docker": True}
    )
    assert monitor.check_peer_heartbeat(probe).ok is expected


@pytest.mark.parametrize("command", [None, "id", "python3 monitor_snapshot.py"])
def test_local_and_unrelated_commands_do_not_create_peer_heartbeat(
    monkeypatch, tmp_path, command
):
    probe = _peer_environment(monkeypatch, tmp_path)
    if command is None:
        monkeypatch.delenv("SSH_ORIGINAL_COMMAND")
    else:
        monkeypatch.setenv("SSH_ORIGINAL_COMMAND", command)
    reporter.record_peer_query({"version": 1, "generated_at": 1000})
    assert not monitor.check_peer_heartbeat(probe).ok
    assert not (tmp_path / ".cache/umc-monitor/last-peer-query.json").exists()


def test_peer_query_proves_liveness_even_when_docker_is_down(
    monkeypatch, tmp_path
):
    probe = _peer_environment(monkeypatch, tmp_path)
    reporter.record_peer_query(
        {"version": 1, "generated_at": 1000, "docker": False}
    )
    assert monitor.check_peer_heartbeat(probe).ok


def test_peer_metadata_contains_no_snapshot_secrets(monkeypatch, tmp_path):
    probe = _peer_environment(monkeypatch, tmp_path)
    data = {"version": 1, "generated_at": 1000, "token": "must-not-record"}
    reporter.record_peer_query(data)
    path = tmp_path / ".cache/umc-monitor/last-peer-query.json"
    assert json.loads(path.read_text()) == {
        "version": 1,
        "generated_at": 1000,
        "source_ip": probe["host"],
    }
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert data["token"] == "must-not-record"


@pytest.mark.parametrize(
    "connection",
    [
        "",
        "bad",
        "not-an-IP 123 31.59.106.143 22",
        "192.0.2.1 123 31.59.106.143 22",
    ],
)
def test_peer_requires_provenance_from_expected_host(
    monkeypatch, tmp_path, connection
):
    probe = _peer_environment(monkeypatch, tmp_path)
    monkeypatch.setenv("SSH_CONNECTION", connection)
    reporter.record_peer_query({"version": 1, "generated_at": 1000})
    assert not monitor.check_peer_heartbeat(probe).ok


@pytest.mark.parametrize("body", [b"bad-secret-json", b"{}", b"x" * 4097])
def test_bad_peer_metadata_is_unhealthy_without_data_leak(
    monkeypatch, tmp_path, body
):
    probe = _peer_environment(monkeypatch, tmp_path)
    path = tmp_path / ".cache/umc-monitor/last-peer-query.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(body)
    result = monitor.check_peer_heartbeat(probe)
    assert not result.ok and "secret" not in result.detail


def test_collect_preserves_https_and_dispatches_peer_probe(
    monkeypatch, tmp_path
):
    https = Mock(return_value=observation(True, "web"))
    peer = Mock(return_value=observation(True, "peer"))
    monkeypatch.setattr(monitor, "check_page", https)
    monkeypatch.setattr(monitor, "check_peer_heartbeat", peer)
    probes = [
        {"name": "web", "url": "https://example.test", "contains": "ok"},
        {"name": "peer", "type": "peer_heartbeat", "host": "192.0.2.1"},
    ]
    result = monitor.collect({"probes": probes, "snapshot": None}, tmp_path)
    assert [x.name for x in result] == ["web", "peer"] and all(
        x.ok for x in result
    )
    https.assert_called_once_with(probes[0])
    peer.assert_called_once_with(probes[1])


def healthy_snapshot(now):
    return {
        "version": 1,
        "generated_at": now,
        "docker": True,
        "services": {"app": "healthy", "app_2": "healthy"},
        "database_ready": True,
        "backup": {"ok": True, "logical": now - 3600, "physical": now - 3500},
    }


@pytest.mark.parametrize(
    "age,good", [(26 * 3600, True), (26 * 3600 + 1, False), (-3600, False)]
)
def test_backup_age_uses_creation_time_not_upload_time(age, good):
    now = 1000000
    data = healthy_snapshot(now)
    data["backup"]["logical"] = now - age
    results = {o.name: o for o in monitor.snapshot_observations(data, now)}
    assert results["Логическая копия"].ok is good


def test_failed_s3_query_is_unknown_not_fabricated_missing_backup():
    data = healthy_snapshot(1000)
    data["backup"] = {
        "ok": False,
        "logical": None,
        "physical": None,
        "failures": 3,
    }
    results = {o.name: o for o in monitor.snapshot_observations(data, 1000)}
    assert not results["Проверка S3"].ok
    assert "Логическая копия" not in results


def test_one_cached_s3_failure_is_not_counted_as_multiple_attempts():
    data = healthy_snapshot(1000)
    data["backup"].update(ok=False, failures=1)
    results = {o.name: o for o in monitor.snapshot_observations(data, 1000)}
    assert "Проверка S3" not in results
    assert results["Логическая копия"].ok


def test_s3_error_streak_counts_distinct_queries_not_cached_reads(
    monkeypatch, tmp_path
):
    execute = Mock(side_effect=RuntimeError("transport"))
    monkeypatch.setattr(reporter, "command", execute)
    cache = tmp_path / "cache.json"
    assert reporter.backup_status(cache, 1000)["failures"] == 1
    assert reporter.backup_status(cache, 1030)["failures"] == 1
    assert execute.call_count == 1
    assert reporter.backup_status(cache, 1060)["failures"] == 2
    assert reporter.backup_status(cache, 1120)["failures"] == 3
    assert execute.call_count == 3


def test_docker_down_does_not_emit_cascading_database_failures():
    results = monitor.snapshot_observations(
        {"version": 1, "generated_at": 1000, "docker": False}, 1000
    )
    assert (
        len(results) == 1 and results[0].name == "Docker" and not results[0].ok
    )


def test_one_healthy_replica_keeps_the_application_available():
    data = healthy_snapshot(1000)
    data["services"]["app"] = "missing"
    results = {o.name: o for o in monitor.snapshot_observations(data, 1000)}
    assert results["Реплики бота"].ok


@pytest.mark.parametrize("stamp", [0, 2000, "bad", None])
def test_stale_or_invalid_source_report_is_not_trusted(stamp):
    data = healthy_snapshot(1000)
    data["generated_at"] = stamp
    with pytest.raises(ValueError):
        monitor.snapshot_observations(data, 1000)


def test_ssh_probe_pins_host_key_and_does_not_use_a_shell(
    monkeypatch, tmp_path
):
    now = monitor.time.time()
    execute = Mock(
        return_value=SimpleNamespace(
            stdout=json.dumps(healthy_snapshot(now)).encode()
        )
    )
    monkeypatch.setattr(monitor.subprocess, "run", execute)
    results = monitor.check_snapshot(
        {
            "host": "192.0.2.1",
            "user": "deploy",
            "known_hosts": "/etc/monitor/known_hosts",
        },
        tmp_path,
    )
    assert all(item.ok for item in results)
    args, kwargs = execute.call_args
    assert "StrictHostKeyChecking=yes" in args[0]
    assert args[0][-1] == "umc-monitor-snapshot"
    assert "shell" not in kwargs


def test_broken_ssh_reports_unknown_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(
        monitor.subprocess,
        "run",
        Mock(side_effect=subprocess.TimeoutExpired("ssh", 28)),
    )
    results = monitor.check_snapshot(
        {"host": "192.0.2.1", "user": "deploy", "known_hosts": "/tmp/hosts"},
        tmp_path,
    )
    assert len(results) == 1 and not results[0].ok
    assert "Docker" not in results[0].name


def config_file(tmp_path, **updates):
    config = {
        "chat_id": "-1001234567890",
        "bot_username": "umc_test_monitor_bot",
        "probes": [
            {
                "name": "Mini App",
                "url": "https://example.org/app.html",
                "contains": "UMC",
            }
        ],
    }
    config.update(updates)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    return path


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org",
        "https://u:p@example.org",
        "https://example.org/?token=secret",
        "file:///etc/passwd",
    ],
)
def test_config_rejects_insecure_or_secret_bearing_probe_urls(tmp_path, url):
    path = config_file(
        tmp_path, probes=[{"name": "probe", "url": url, "contains": "UMC"}]
    )
    with pytest.raises(ValueError):
        monitor.load_config(path)


def test_example_config_and_state_validation(tmp_path):
    sample = (
        Path(__file__).parents[2]
        / "config/monitoring/external-monitor.example.json"
    )
    assert len(monitor.load_config(sample)["probes"]) == 2
    assert monitor.load_state(tmp_path / "missing") == {"checks": {}}
    path = tmp_path / "state.json"
    path.write_text('{"checks": {"bad": {}}}')
    with pytest.raises(ValueError):
        monitor.load_state(path)


def test_peer_config_needs_no_ssh_credential_or_web_endpoint():
    sample = (
        Path(__file__).parents[2]
        / "config/monitoring/peer-monitor.example.json"
    )
    config = monitor.load_config(sample)
    assert config["probes"] == [
        {
            "name": "Связь с монитором Timeweb (проверка с UMC)",
            "type": "peer_heartbeat",
            "host": "194.87.131.138",
        }
    ]
    assert config["snapshot"] is None


@pytest.mark.parametrize(
    "host", ["example.org", "192.0.2.1:22", "192.0.2.1; id"]
)
def test_peer_config_requires_a_literal_ip_address(tmp_path, host):
    path = config_file(
        tmp_path,
        probes=[{"name": "peer", "type": "peer_heartbeat", "host": host}],
    )
    with pytest.raises(ValueError):
        monitor.load_config(path)


def test_unknown_probe_type_is_rejected_before_transport(tmp_path):
    path = config_file(
        tmp_path,
        probes=[{"name": "peer", "type": "shell", "host": "192.0.2.1"}],
    )
    with pytest.raises(ValueError, match="unknown_probe_type"):
        monitor.load_config(path)


@pytest.mark.parametrize(
    "username", ["usemycontent_ai", "umc_alerts_app", "umc_alerts_bot"]
)
def test_bot_username_suffix_does_not_replace_api_identity_check(
    tmp_path, monkeypatch, username
):
    config = monitor.load_config(config_file(tmp_path, bot_username=username))
    api = Mock(
        side_effect=[
            {"id": 123, "is_bot": True, "username": username},
            {"type": "channel"},
            {"status": "administrator", "can_post_messages": True},
        ]
    )
    monkeypatch.setattr(monitor, "telegram", api)
    monitor.validate_recipient(
        "123:fake", str(config["chat_id"]), config["bot_username"]
    )
    assert [call.args[1] for call in api.call_args_list] == [
        "getMe",
        "getChat",
        "getChatMember",
    ]


def test_non_bot_identity_is_rejected_before_channel_access(monkeypatch):
    api = Mock(
        return_value={"id": 123, "is_bot": False, "username": "usemycontent_ai"}
    )
    monkeypatch.setattr(monitor, "telegram", api)
    with pytest.raises(ValueError, match="bot_identity_required"):
        monitor.validate_recipient(
            "123:fake", "-1001234567890", "usemycontent_ai"
        )
    assert api.call_count == 1


def test_channel_permission_is_checked_without_sending(monkeypatch):
    api = Mock(
        side_effect=[
            {"id": 123, "is_bot": True},
            {"type": "channel"},
            {"status": "administrator", "can_post_messages": True},
        ]
    )
    monkeypatch.setattr(monitor, "telegram", api)
    monitor.validate_recipient("123:fake", "-1001234567890")
    assert [call.args[1] for call in api.call_args_list] == [
        "getMe",
        "getChat",
        "getChatMember",
    ]


def test_personal_chat_is_never_used_instead_of_the_channel(monkeypatch):
    monkeypatch.setattr(
        monitor,
        "telegram",
        Mock(side_effect=[{"id": 123, "is_bot": True}, {"type": "private"}]),
    )
    with pytest.raises(ValueError, match="channel"):
        monitor.validate_recipient("123:fake", "123456789")


@pytest.mark.parametrize("recovered_before_retry", [False, True])
def test_run_retries_failed_delivery_or_clears_recovered_incident(
    monkeypatch, tmp_path, recovered_before_retry
):
    credentials = tmp_path / "creds"
    credentials.mkdir()
    (credentials / "telegram_token").write_text("123:fake")
    monkeypatch.setattr(monitor, "validate_recipient", Mock())
    samples = iter(
        [
            [observation()],
            [observation()],
            [observation(recovered_before_retry)],
            [observation(True)],
        ]
    )
    monkeypatch.setattr(
        monitor, "collect", lambda config, credentials: next(samples)
    )
    clock = iter(
        [100, 130, 160, 190] if recovered_before_retry else [100, 130, 500, 530]
    )
    ticks = []

    class StopLoop(Exception):
        pass

    def sleep(seconds):
        ticks.append(seconds)
        if len(ticks) == 4:
            raise StopLoop

    monkeypatch.setattr(
        monitor,
        "time",
        SimpleNamespace(
            time=lambda: next(clock), monotonic=lambda: 0, sleep=sleep
        ),
    )
    api = Mock(side_effect=[ConnectionError("hidden-secret"), {}, {}])
    monkeypatch.setattr(monitor, "telegram", api)
    path = tmp_path / "state.json"
    with pytest.raises(StopLoop):
        monitor.run(
            {
                "chat_id": "-1001234567890",
                "bot_username": "umc_test_monitor_bot",
            },
            credentials,
            path,
        )
    assert api.call_count == (1 if recovered_before_retry else 3)
    if not recovered_before_retry:
        assert "ВОССТАНОВЛЕНО" in api.call_args.args[2]["text"]
    assert monitor.load_state(path)["retry_at"] == 0
    assert monitor.load_state(path)["checks"]["Mini App"]["notified"] is False


def test_snapshot_docker_failure_does_not_query_database_or_s3(
    monkeypatch, tmp_path
):
    execute = Mock(side_effect=RuntimeError("secret"))
    monkeypatch.setattr(reporter, "command", execute)
    result = reporter.snapshot(tmp_path / "cache.json")
    assert result["docker"] is False and execute.call_count == 1


def test_s3_cache_avoids_queries_and_preserves_last_good_on_error(
    monkeypatch, tmp_path
):
    cache = tmp_path / "cache.json"
    cache.write_text(
        json.dumps(
            {"ok": True, "logical": 100, "physical": 110, "checked_at": 200}
        )
    )
    execute = Mock(side_effect=RuntimeError("AWS-secret-in-exception"))
    monkeypatch.setattr(reporter, "command", execute)
    assert reporter.backup_status(cache, 300)["ok"] is True
    execute.assert_not_called()
    result = reporter.backup_status(cache, 1000)
    assert result["ok"] is False and result["logical"] == 100
    assert "secret" not in cache.read_text()


def test_s3_query_does_not_confuse_recent_upload_with_new_backup(
    monkeypatch, capsys, tmp_path
):
    now = datetime.now(timezone.utc)
    old = (now - timedelta(hours=30)).strftime("%Y%m%d_%H%M%S")
    future = (now + timedelta(days=1)).strftime("%Y%m%d_%H%M%S")
    client = Mock()

    def pages(**kwargs):
        if kwargs["Prefix"] == "backups/":
            return [
                {
                    "Contents": [
                        {
                            "Key": f"backups/ugc_backup_{old}.sql.gz",
                            "Size": 100,
                        },
                        {
                            "Key": f"backups/ugc_backup_{future}.sql.gz",
                            "Size": 100,
                        },
                        {"Key": "backups/unrelated.txt", "Size": 100},
                    ]
                }
            ]
        return [{}]

    client.get_paginator.return_value.paginate.side_effect = pages
    payload = b"x" * 100
    (tmp_path / f"ugc_backup_{old}.sql.gz").write_bytes(payload)
    monkeypatch.setenv("UMC_MONITOR_BACKUP_ROOT", str(tmp_path))
    client.head_object.return_value = {
        "ContentLength": 100,
        "Metadata": {"sha256": hashlib.sha256(payload).hexdigest()},
        "ETag": '"' + hashlib.md5(payload).hexdigest() + '"',
    }
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: client)
    for key in [
        "S3_ENDPOINT_URL",
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
        "S3_BUCKET",
    ]:
        monkeypatch.setenv(key, "fake")
    exec(reporter.S3_QUERY, {})
    result = json.loads(capsys.readouterr().out)
    assert result["logical"] < now.timestamp() - monitor.MAX_BACKUP_AGE
    assert result["physical"] is None
    client.get_object.assert_not_called()
    client.download_file.assert_not_called()


def test_scripts_parse_on_vps_python_312():
    root = Path(__file__).parents[2]
    for name in ["external_monitor.py", "monitor_snapshot.py"]:
        ast.parse(
            (root / "scripts" / name).read_text(), feature_version=(3, 12)
        )


def test_wrong_bot_token_is_rejected_before_saving_or_sending(monkeypatch):
    api = Mock(
        return_value={"id": 1, "is_bot": True, "username": "working_ugc_bot"}
    )
    monkeypatch.setattr(monitor, "telegram", api)
    with pytest.raises(ValueError, match="unexpected_bot_identity"):
        monitor.validate_recipient(
            "1:fake", "-1001234567890", "umc_monitor_bot"
        )
    assert api.call_count == 1


@pytest.mark.parametrize(
    "etag_valid,sha_valid,expected",
    [(True, True, True), (False, True, False), (True, False, False)],
)
def test_s3_confirmation_requires_payload_etag_and_local_sha(
    monkeypatch, tmp_path, capsys, etag_valid, sha_valid, expected
):
    now = datetime.now(timezone.utc) - timedelta(minutes=5)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    name = f"ugc_backup_{stamp}.sql.gz"
    payload = b"test payload" * 10
    (tmp_path / name).write_bytes(payload)
    client = Mock()
    client.get_paginator.return_value.paginate.side_effect = [
        [{"Contents": [{"Key": "backups/" + name, "Size": len(payload)}]}],
        [{}],
    ]
    client.head_object.return_value = {
        "ContentLength": len(payload),
        "Metadata": {
            "sha256": hashlib.sha256(payload).hexdigest()
            if sha_valid
            else "a" * 64
        },
        "ETag": hashlib.md5(payload).hexdigest() if etag_valid else "wrong",
    }
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: client)
    monkeypatch.setenv("UMC_MONITOR_BACKUP_ROOT", str(tmp_path))
    for key in [
        "S3_ENDPOINT_URL",
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
        "S3_BUCKET",
    ]:
        monkeypatch.setenv(key, "fake")
    exec(reporter.S3_QUERY, {})
    result = json.loads(capsys.readouterr().out)
    assert (result["logical"] is not None) is expected
    client.get_object.assert_not_called()


def test_s3_only_checks_newest_confirmed_copy(monkeypatch, tmp_path, capsys):
    now = datetime.now(timezone.utc)
    names = [
        "ugc_backup_"
        + (now - timedelta(hours=n)).strftime("%Y%m%d_%H%M%S")
        + ".sql.gz"
        for n in [1, 2, 3]
    ]
    payload = b"copy"
    for name in names:
        (tmp_path / name).write_bytes(payload)
    client = Mock()
    client.get_paginator.return_value.paginate.side_effect = [
        [
            {
                "Contents": [
                    {"Key": "backups/" + name, "Size": 4}
                    for name in reversed(names)
                ]
            }
        ],
        [{}],
    ]
    client.head_object.return_value = {
        "ContentLength": 4,
        "Metadata": {"sha256": hashlib.sha256(payload).hexdigest()},
        "ETag": hashlib.md5(payload).hexdigest(),
    }
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: client)
    monkeypatch.setenv("UMC_MONITOR_BACKUP_ROOT", str(tmp_path))
    for key in [
        "S3_ENDPOINT_URL",
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
        "S3_BUCKET",
    ]:
        monkeypatch.setenv(key, "fake")
    exec(reporter.S3_QUERY, {})
    capsys.readouterr()
    assert client.head_object.call_count == 1
    assert client.head_object.call_args.kwargs["Key"] == "backups/" + names[0]
