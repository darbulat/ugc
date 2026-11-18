"""Read-only Meta token checks and durable Telegram expiry notifications.

This process never refreshes credentials or calls creator/verification writers.
Its only external writes are notifications to the explicitly configured admins.
"""

import argparse
import fcntl
import hashlib
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import httpx
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    model_validator,
)

UTC = timezone.utc
MOSCOW = ZoneInfo("Europe/Moscow")


class TokenSpec(BaseModel):
    """An expiry date is usable only for the exact credential it describes."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    key: Literal["verification", "discovery"]
    purpose: str = Field(min_length=1, max_length=120)
    kind: Literal["instagram_login", "facebook_user"]
    token: SecretStr = Field(default=SecretStr(""), repr=False)
    app_id: str = ""
    expected_username: str = "usemycontent"
    required_scopes: list[str] = Field(default_factory=list)
    expires_at: AwareDatetime | None = None
    expiry_fingerprint: str = ""

    @property
    def fingerprint(self) -> str:
        value = self.token.get_secret_value()
        return (
            hashlib.sha256(value.encode()).hexdigest() if value else "missing"
        )

    @property
    def recorded_expiry(self) -> datetime | None:
        if self.expiry_fingerprint == self.fingerprint:
            return self.expires_at
        return None


class MonitorSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    bot_token: SecretStr = Field(repr=False, min_length=1)
    recipients: list[str]
    tokens: list[TokenSpec]

    @model_validator(mode="after")
    def validate_targets(self) -> "MonitorSettings":
        if not 1 <= len(self.recipients) <= 3 or len(
            set(self.recipients)
        ) != len(self.recipients):
            raise ValueError("One to three distinct admin recipients required")
        if any(not value.isdecimal() for value in self.recipients):
            raise ValueError(
                "Admin recipients must be private Telegram chat IDs"
            )
        if {token.key for token in self.tokens} != {
            "verification",
            "discovery",
        } or len(self.tokens) != 2:
            raise ValueError("Exactly the two approved token purposes required")
        return self


@dataclass(frozen=True)
class Observation:
    health: Literal["valid", "invalid", "unavailable", "missing"]
    expires_at: datetime | None


def _timestamp(value: object) -> datetime | None:
    if type(value) is not int or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value, UTC)
    except (ValueError, OverflowError, OSError):
        return None


def inspect_token(
    client: httpx.Client,
    spec: TokenSpec,
    previous_expiry: datetime | None = None,
) -> Observation:
    """Use fixed Meta endpoints; unsupported introspection is not validity."""
    fallback = spec.recorded_expiry or previous_expiry
    secret = spec.token.get_secret_value()
    if not secret:
        return Observation("missing", None)
    if spec.kind == "instagram_login":
        url = "https://graph.instagram.com/v24.0/me"
        params = {"fields": "user_id,username"}
    else:
        url = "https://graph.facebook.com/v27.0/debug_token"
        params = {"input_token": secret}
    try:
        response = client.get(
            url, params=params, headers={"Authorization": "Bearer " + secret}
        )
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return Observation("unavailable", fallback)
    if not isinstance(body, dict):
        return Observation("unavailable", fallback)
    error = body.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    if code in {190, 10, 200}:
        return Observation("invalid", fallback)
    if response.status_code != 200 or error:
        return Observation("unavailable", fallback)
    if spec.kind == "instagram_login":
        matches = body.get("username") == spec.expected_username
        return Observation("valid" if matches else "invalid", fallback)
    data = body.get("data")
    if not isinstance(data, dict):
        return Observation("unavailable", fallback)
    scopes = data.get("scopes")
    valid = (
        data.get("is_valid") is True
        and data.get("app_id") == spec.app_id
        and isinstance(scopes, list)
        and all(isinstance(scope, str) for scope in scopes)
        and set(spec.required_scopes).issubset(scopes)
    )
    if not valid:
        return Observation("invalid", fallback)
    dates = [
        date
        for key in ("expires_at", "data_access_expires_at")
        if (date := _timestamp(data.get(key))) is not None
    ]
    return Observation("valid", min(dates) if dates else fallback)


def alert_kind(
    observation: Observation, now: datetime, failures: int
) -> str | None:
    expiry = observation.expires_at
    if expiry is not None and expiry <= now:
        return "expired"
    if observation.health in {"invalid", "missing"}:
        return observation.health
    if expiry is not None:
        remaining = expiry - now
        if remaining <= timedelta(days=1):
            return "one_day"
        if remaining <= timedelta(days=7):
            return "seven_days"
    if observation.health == "unavailable":
        return "check_unavailable" if failures >= 3 else None
    return "expiry_unknown" if expiry is None else None


def message_text(spec: TokenSpec, observation: Observation, kind: str) -> str:
    descriptions = {
        "seven_days": "До истечения токена осталось не более 7 дней.",
        "one_day": "До истечения токена осталось не более суток.",
        "expired": (
            "Записанный срок действия токена истёк. Нужно проверить доступ."
        ),
        "invalid": "Meta сообщает о потере доступа или необходимых прав.",
        "missing": "Токен для контроля не настроен.",
        "expiry_unknown": (
            "Доступ подтверждён, но срок токена неизвестен. "
            "Предупреждения за 7 дней и за сутки требуют подтверждённой даты."
        ),
        "check_unavailable": "Три проверки Meta подряд не дали результата.",
    }
    text = f"⚠️ UMC · {spec.purpose}\n\n{descriptions[kind]}"
    if observation.expires_at is not None:
        date = observation.expires_at.astimezone(MOSCOW)
        text += f"\nСрок: {date:%d.%m.%Y %H:%M} МСК."
    text += "\nАккаунт: @" + spec.expected_username
    if spec.key == "discovery":
        text += (
            "\nЭто отдельный доступ к статистике. "
            "Рабочий токен верификации проверяется отдельно."
        )
    text += (
        "\n\nНужно проверить доступ в Meta и подтверждённый срок. "
        "Мониторинг не продлевает и не заменяет токены."
    )
    return text


class MonitorState:
    """SQLite state is local to this one process, outside the working DB."""

    def __init__(self, path: Path):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=2)
        self.db.executescript(
            "CREATE TABLE IF NOT EXISTS delivered "
            "(event TEXT, recipient TEXT, sent_at TEXT, "
            "PRIMARY KEY(event,recipient));"
            "CREATE TABLE IF NOT EXISTS observations "
            "(key TEXT PRIMARY KEY, payload TEXT NOT NULL);"
        )

    def read(self, key: str) -> dict:
        row = self.db.execute(
            "SELECT payload FROM observations WHERE key=?", (key,)
        ).fetchone()
        return json.loads(row[0]) if row else {}

    def write(self, key: str, payload: dict) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO observations VALUES (?,?) ON CONFLICT(key) "
                "DO UPDATE SET payload=excluded.payload",
                (key, json.dumps(payload)),
            )

    def delivered(self, event: str, recipient: str) -> bool:
        return (
            self.db.execute(
                "SELECT 1 FROM delivered WHERE event=? AND recipient=?",
                (event, recipient),
            ).fetchone()
            is not None
        )

    def mark_sent(self, event: str, recipient: str, now: datetime) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO delivered VALUES (?,?,?)",
                (event, recipient, now.isoformat()),
            )

    def close(self) -> None:
        self.db.close()


def send_alert(
    client: httpx.Client, bot_token: SecretStr, recipient: str, text: str
) -> bool:
    try:
        response = client.post(
            "https://api.telegram.org/bot"
            + bot_token.get_secret_value()
            + "/sendMessage",
            json={"chat_id": recipient, "text": text},
        )
        body = response.json()
        return (
            response.status_code == 200
            and isinstance(body, dict)
            and body.get("ok") is True
        )
    except (httpx.HTTPError, ValueError):
        return False


def run_once(
    settings: MonitorSettings,
    state: MonitorState,
    client: httpx.Client,
    now: datetime,
    *,
    dry_run: bool = False,
) -> dict:
    results = []
    for spec in settings.tokens:
        previous = state.read(spec.key)
        same = previous.get("fingerprint") == spec.fingerprint
        previous_date = previous.get("expires_at") if same else None
        cached = (
            datetime.fromisoformat(previous_date) if previous_date else None
        )
        observation = inspect_token(client, spec, cached)
        failures = (
            (previous.get("failures", 0) if same else 0) + 1
            if observation.health == "unavailable"
            else 0
        )
        kind = alert_kind(observation, now, failures)
        episode = previous.get("episode", 0)
        if not same or previous.get("kind") != kind:
            episode += 1
        expiry = (
            observation.expires_at.isoformat()
            if observation.expires_at is not None
            else None
        )
        event_parts = [spec.key, spec.fingerprint, expiry, kind]
        if kind in {
            "invalid",
            "missing",
            "expiry_unknown",
            "check_unavailable",
        }:
            event_parts.append(episode)
        event = hashlib.sha256(json.dumps(event_parts).encode()).hexdigest()
        sent = failed = 0
        if kind is not None:
            text = message_text(spec, observation, kind)
            for recipient in settings.recipients:
                if state.delivered(event, recipient) or dry_run:
                    continue
                if send_alert(client, settings.bot_token, recipient, text):
                    state.mark_sent(event, recipient, now)
                    sent += 1
                else:
                    failed += 1
        if not dry_run:
            state.write(
                spec.key,
                {
                    "fingerprint": spec.fingerprint,
                    "expires_at": expiry,
                    "health": observation.health,
                    "kind": kind,
                    "failures": failures,
                    "episode": episode,
                },
            )
        results.append(
            {
                "token": spec.key,
                "health": observation.health,
                "expires_at": expiry,
                "alert": kind,
                "sent": sent,
                "delivery_errors": failed,
            }
        )
    if not dry_run:
        state.write("heartbeat", {"checked_at": now.isoformat()})
    return {"checked_at": now.isoformat(), "tokens": results}


def health_check(state_path: Path, now: datetime) -> bool:
    if not state_path.exists():
        return False
    state = MonitorState(state_path)
    try:
        value = state.read("heartbeat").get("checked_at")
        return bool(
            value
            and timedelta(0)
            <= now - datetime.fromisoformat(value)
            <= timedelta(hours=2)
        )
    finally:
        state.close()


def main() -> None:  # pragma: no cover - CLI process boundary
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--health", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    state_path = Path(
        os.environ.get("META_TOKEN_MONITOR_STATE", "/state/monitor.sqlite3")
    )
    if args.health:
        raise SystemExit(
            0 if health_check(state_path, datetime.now(UTC)) else 1
        )
    settings_path = Path(
        os.environ.get("META_TOKEN_MONITOR_SETTINGS", "/settings/settings.json")
    )
    state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = (state_path.parent / "monitor.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    logging.getLogger("httpcore").setLevel(logging.CRITICAL)
    state = MonitorState(state_path)
    try:
        with httpx.Client(
            timeout=10, trust_env=False, follow_redirects=False
        ) as client:
            while True:
                settings = MonitorSettings.model_validate_json(
                    settings_path.read_text()
                )
                result = run_once(
                    settings,
                    state,
                    client,
                    datetime.now(UTC),
                    dry_run=args.dry_run,
                )
                print(json.dumps(result), flush=True)
                if args.once or args.dry_run:
                    return
                time.sleep(3600)
    finally:
        state.close()
        lock.close()


if __name__ == "__main__":  # pragma: no cover
    main()
