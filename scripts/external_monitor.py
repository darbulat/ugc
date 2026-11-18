#!/usr/bin/env python3
"""Small external monitor. Python stdlib only; never imports the UMC app.

Run on an independent host. Secrets come from systemd LoadCredential, not
configuration, command arguments, logs, or the production application's bot.
"""

from __future__ import annotations

import argparse
import getpass
import ipaddress
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_BODY = 131072
MAX_BACKUP_AGE = 26 * 3600


@dataclass(frozen=True)
class Observation:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class Event:
    name: str
    recovered: bool
    detail: str


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A redirect to login or a different site must not hide a failed probe.
        return None


def request_bytes(url: str, data: bytes | None = None) -> bytes:
    request = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": "UMC-External-Monitor/1.0"},
    )
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(request, timeout=8) as response:
        if response.status != 200:
            raise ValueError("unexpected_status")
        return response.read(MAX_BODY)


def check_page(probe: dict[str, str]) -> Observation:
    try:
        body = request_bytes(probe["url"]).decode("utf-8", errors="replace")
        if probe["contains"] not in body:
            return Observation(
                probe["name"],
                False,
                "Страница не содержит ожидаемого содержимого",
            )
        return Observation(probe["name"], True, "Страница доступна")
    except Exception:
        # Exception strings can contain URLs, credentials or response bodies.
        return Observation(probe["name"], False, "HTTPS-проверка не прошла")


def snapshot_observations(
    data: dict[str, Any], now: float
) -> list[Observation]:
    generated = data.get("generated_at")
    if (
        data.get("version") != 1
        or not isinstance(generated, (int, float))
        or not -30 <= now - generated <= 120
    ):
        raise ValueError("stale_or_invalid_snapshot")
    docker_ok = data.get("docker") is True
    observations = [
        Observation("Docker", docker_ok, "Проверка Docker на уровне ОС")
    ]
    if not docker_ok:
        return observations
    services = data.get("services", {})
    observations.extend(
        [
            Observation(
                "Реплики бота",
                any(services.get(x) == "healthy" for x in ("app", "app_2")),
                "Нет здоровой реплики приложения",
            ),
            Observation(
                "База и админка",
                data.get("database_ready") is True,
                "База не прошла внутреннюю проверку SELECT 1",
            ),
        ]
    )
    backup = data.get("backup", {})
    # Unknown/transient reads neither open nor resolve an S3 incident. Count
    # distinct source attempts, not repeatedly polling one cached failure.
    if backup.get("ok") is True or backup.get("failures", 0) >= 3:
        observations.append(
            Observation(
                "Проверка S3",
                backup.get("ok") is True,
                "Не удалось проверить копии в S3",
            )
        )
    for kind, label in (
        ("logical", "Логическая копия"),
        ("physical", "Физическая копия"),
    ):
        created = backup.get(kind)
        # Failed S3 queries are reported as unknown, never as a fabricated age.
        if created is None and not backup.get("ok"):
            continue
        valid = (
            isinstance(created, (int, float))
            and -30 <= now - created <= MAX_BACKUP_AGE
        )
        observations.append(
            Observation(
                label, valid, "Нет подтверждённой копии моложе 26 часов"
            )
        )
    return observations


def check_snapshot(
    config: dict[str, str], credentials: Path
) -> list[Observation]:
    command = [
        "/usr/bin/ssh",
        "-T",
        "-n",
        "-o",
        "BatchMode=yes",
        "-F",
        "/dev/null",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "ClearAllForwardings=yes",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "UserKnownHostsFile=" + config["known_hosts"],
        "-i",
        str(credentials / "reporter_key"),
        config["user"] + "@" + config["host"],
        "umc-monitor-snapshot",
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, timeout=28, check=True
        )
        if len(result.stdout) > 32768:
            raise ValueError("oversized_snapshot")
        observations = snapshot_observations(
            json.loads(result.stdout), time.time()
        )
        return [
            Observation("Сводка сервера", True, "Получена свежая сводка")
        ] + observations
    except Exception:
        return [
            Observation(
                "Сводка сервера",
                False,
                "Недоступна защищённая проверка Docker, БД и S3",
            )
        ]


def evaluate(
    state: dict[str, Any],
    observations: list[Observation],
    now: float,
    *,
    failures: int = 2,
    repeat_seconds: int = 14400,
) -> list[Event]:
    events = []
    checks = state.setdefault("checks", {})
    for observation in observations:
        entry = checks.setdefault(
            observation.name, {"bad": 0, "notified": False, "sent_at": 0}
        )
        entry["bad"] = 0 if observation.ok else min(entry["bad"] + 1, failures)
        if observation.ok and entry["notified"]:
            events.append(Event(observation.name, True, observation.detail))
        elif (
            not observation.ok
            and entry["bad"] >= failures
            and (
                not entry["notified"]
                or now - entry["sent_at"] >= repeat_seconds
            )
        ):
            events.append(Event(observation.name, False, observation.detail))
    return events


def acknowledge(state: dict[str, Any], events: list[Event], now: float) -> None:
    # Called only after Telegram explicitly confirms delivery acceptance.
    for event in events:
        state["checks"][event.name].update(
            notified=not event.recovered, sent_at=now
        )


def format_message(events: list[Event]) -> str:
    lines = ["UMC · внешний мониторинг"]
    for event in events:
        status = "ВОССТАНОВЛЕНО" if event.recovered else "ПРОБЛЕМА"
        detail = "Проверка снова проходит" if event.recovered else event.detail
        lines.append(f"{status}: {event.name} — {detail}")
    return "\n".join(lines)[:3900]


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"checks": {}}
    state = json.loads(path.read_text())
    if not isinstance(state.get("checks"), dict):
        raise ValueError("invalid_state")
    for entry in state["checks"].values():
        if not isinstance(entry, dict) or not isinstance(entry.get("bad"), int):
            raise ValueError("invalid_check_state")
        if not isinstance(entry.get("notified"), bool) or not isinstance(
            entry.get("sent_at"), (int, float)
        ):
            raise ValueError("invalid_check_state")
    return state


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text())
    probes = config.get("probes", [])
    if not 1 <= len(probes) <= 5:
        raise ValueError("one_to_five_probes_required")
    names = []
    for probe in probes:
        url = urllib.parse.urlsplit(probe["url"])
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("public_https_url_required")
        if not probe.get("contains") or not 1 <= len(probe["name"]) <= 80:
            raise ValueError("invalid_probe")
        names.append(probe["name"])
    if len(set(names)) != len(names):
        raise ValueError("duplicate_probe_names")
    username = config.get("bot_username", "")
    if not re.fullmatch(r"[A-Za-z0-9_]{5,64}", username):
        raise ValueError("dedicated_bot_username_required")
    if not re.fullmatch(r"-100[0-9]{5,}", str(config.get("chat_id", ""))):
        raise ValueError("channel_or_supergroup_id_required")
    snapshot = config.get("snapshot")
    if snapshot:
        ipaddress.ip_address(snapshot["host"])
        if not re.fullmatch(r"[a-z_][a-z0-9_-]*", snapshot["user"]):
            raise ValueError("invalid_reporter_user")
    return config


def telegram(
    token: str, method: str, payload: dict[str, Any]
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
        raise ValueError("invalid_telegram_token")
    request = urllib.request.Request(
        "https://api.telegram.org/bot" + token + "/" + method,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.loads(response.read(65536))
    if data.get("ok") is not True:
        raise ValueError("telegram_request_not_accepted")
    return data["result"]


def validate_recipient(
    token: str, chat_id: str, expected_bot: str | None = None
) -> None:
    identity = telegram(token, "getMe", {})
    if identity.get("is_bot") is not True:
        raise ValueError("bot_identity_required")
    if (
        expected_bot
        and identity.get("username", "").lower() != expected_bot.lower()
    ):
        raise ValueError("unexpected_bot_identity")
    chat = telegram(token, "getChat", {"chat_id": chat_id})
    if chat.get("type") not in ("channel", "supergroup"):
        raise ValueError("private_alert_channel_required")
    member = telegram(
        token, "getChatMember", {"chat_id": chat_id, "user_id": identity["id"]}
    )
    if member.get("status") not in ("administrator", "creator"):
        raise ValueError("bot_needs_publication_right")
    if (
        chat["type"] == "channel"
        and member.get("can_post_messages") is not True
    ):
        raise ValueError("bot_cannot_post_to_channel")


def ping_watchdog(credentials: Path) -> None:
    path = credentials / "watchdog_url"
    if not path.exists():
        return
    url = path.read_text().strip()
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "hc-ping.com":
        raise ValueError("invalid_external_watchdog_url")
    request_bytes(url)


def collect(config: dict[str, Any], credentials: Path) -> list[Observation]:
    with ThreadPoolExecutor(max_workers=6) as pool:
        pages = [pool.submit(check_page, probe) for probe in config["probes"]]
        snapshot = (
            pool.submit(check_snapshot, config["snapshot"], credentials)
            if config.get("snapshot")
            else None
        )
        observations = [future.result() for future in pages]
        if snapshot is not None:
            observations.extend(snapshot.result())
    return observations


def run(config: dict[str, Any], credentials: Path, state_path: Path) -> None:
    token = (credentials / "telegram_token").read_text().strip()
    validate_recipient(token, str(config["chat_id"]), config["bot_username"])
    state = load_state(state_path)
    checked_at = 0.0
    recipient_ok = True
    while True:
        start = time.monotonic()
        observations = collect(config, credentials)
        now = time.time()
        if now - checked_at >= 300:
            try:
                validate_recipient(
                    token, str(config["chat_id"]), config["bot_username"]
                )
                recipient_ok = True
            except Exception:
                recipient_ok = False
                print("recipient_validation_failed", flush=True)
            checked_at = now
        events = evaluate(state, observations, now)
        if events and now >= state.get("retry_at", 0):
            try:
                telegram(
                    token,
                    "sendMessage",
                    {
                        "chat_id": config["chat_id"],
                        "text": format_message(events),
                        "disable_web_page_preview": True,
                    },
                )
                acknowledge(state, events, now)
                state["retry_at"] = 0
            except Exception as error:
                state["retry_at"] = now + 300
                print("notification_failed:" + type(error).__name__, flush=True)
        state["last_cycle"] = now
        atomic_json(state_path, state)
        if (
            recipient_ok
            and not state.get("retry_at")
            and now - state.get("watchdog_at", 0) >= 240
        ):
            try:
                ping_watchdog(credentials)
                state["watchdog_at"] = now
            except Exception as error:
                print("watchdog_failed:" + type(error).__name__, flush=True)
        print(
            json.dumps(
                {
                    "checks": len(observations),
                    "failed": sum(not item.ok for item in observations),
                }
            ),
            flush=True,
        )
        time.sleep(max(1, 30 - (time.monotonic() - start)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Read-only probes; no Telegram calls",
    )
    parser.add_argument(
        "--configure-token",
        action="store_true",
        help="Root-only interactive token input; no messages",
    )
    args = parser.parse_args()
    config = load_config(args.config)
    if args.configure_token:
        if os.geteuid() != 0:
            raise ValueError("root_required_for_credential_setup")
        token = getpass.getpass(
            "Токен отдельного бота оповещений (ввод скрыт): "
        ).strip()
        validate_recipient(
            token, str(config["chat_id"]), config["bot_username"]
        )
        destination = args.config.parent / "telegram-token"
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(token)
        print(
            "Токен проверен и сохранён с правами 0600. "
            "Сообщения не отправлялись."
        )
        return
    credentials = Path(
        os.environ.get(
            "CREDENTIALS_DIRECTORY",
            "/run/credentials/umc-external-monitor.service",
        )
    )
    if args.check:
        print(
            json.dumps(
                [item.__dict__ for item in collect(config, credentials)],
                ensure_ascii=False,
            )
        )
        return
    run(
        config,
        credentials,
        Path(os.environ.get("STATE_DIRECTORY", "/var/lib/umc-external-monitor"))
        / "state.json",
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("monitor_stopped:" + type(error).__name__, flush=True)
        raise SystemExit(1) from None
