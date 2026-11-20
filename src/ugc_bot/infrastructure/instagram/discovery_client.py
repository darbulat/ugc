"""One bounded Business Discovery request; no verification credentials."""

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr

from ugc_bot.domain.instagram_discovery import (
    HANDLE,
    DiscoveryDiagnostic,
    DiscoveryProfile,
    DiscoveryResult,
)

FIELDS = (
    "id,username,followers_count,media_count,follows_count,biography,"
    "has_profile_pic,name,website,profile_picture_url"
)
STOP_OUTCOMES = frozenset(
    {
        "credentials",
        "rate_limit",
        "invalid_request",
        "network",
        "provider_error",
    }
)


class DiscoveryCredential(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    # This pilot is authorized only for the UMC app and its business account.
    app_id: Literal["1528779102424926"]
    business_id: Literal["17841436959803981"]
    token: SecretStr = Field(repr=False, min_length=1)
    expires_at: AwareDatetime
    expiry_fingerprint: str

    @property
    def context(self) -> str:
        return f"facebook_login:{self.app_id}:{self.business_id}"

    @classmethod
    def load(cls, path: Path) -> "DiscoveryCredential":
        if path.stat().st_mode & 0o077:
            raise ValueError(
                "Discovery credential must have owner-only permissions"
            )
        credential = cls.model_validate_json(path.read_bytes())
        fingerprint = hashlib.sha256(
            credential.token.get_secret_value().encode()
        ).hexdigest()
        if (
            credential.expiry_fingerprint != fingerprint
            or credential.expires_at <= datetime.now(timezone.utc)
        ):
            raise ValueError(
                "Discovery credential expiry is unknown or expired"
            )
        return credential


def _usage_values(item):
    if isinstance(item, dict):
        for key, value in item.items():
            if key in {"call_count", "total_cputime", "total_time"}:
                if (
                    type(value) not in {int, float}
                    or not math.isfinite(value)
                    or value < 0
                ):
                    yield 100.0
                else:
                    yield float(value)
            else:
                yield from _usage_values(value)
    elif isinstance(item, list):
        for value in item:
            yield from _usage_values(value)


def _usage(headers: httpx.Headers) -> float:
    percentages = [0.0]
    try:
        for name in (
            "x-app-usage",
            "x-business-use-case-usage",
            "x-page-usage",
        ):
            if name in headers:
                percentages.extend(_usage_values(json.loads(headers[name])))
    except (ValueError, TypeError):
        return 100.0
    return max(percentages)


def _profile(data: dict) -> DiscoveryProfile | None:
    object_id, username = data.get("id"), data.get("username")
    if (
        not isinstance(object_id, str)
        or not object_id.isdecimal()
        or len(object_id) > 100
    ):
        return None
    if not isinstance(username, str) or not HANDLE.fullmatch(username):
        return None
    details = {}
    for key in ("biography", "name", "website", "profile_picture_url"):
        value = data.get(key)
        if isinstance(value, str) and len(value) <= 10000:
            details[key] = value
    if type(data.get("has_profile_pic")) is bool:
        details["has_profile_pic"] = data["has_profile_pic"]
    for key in ("follows_count",):
        if type(data.get(key)) is int and data[key] >= 0:
            details[key] = data[key]

    def count(key):
        value = data.get(key)
        return value if type(value) is int and 0 <= value <= 2**63 - 1 else None

    return DiscoveryProfile(
        object_id,
        username,
        count("followers_count"),
        count("media_count"),
        details,
    )


def _diagnostic(status: int, error: dict | None = None) -> DiscoveryDiagnostic:
    error = error or {}

    def code(key):
        value = error.get(key)
        return value if type(value) is int and 0 <= value < 2**31 else None

    transient = error.get("is_transient")
    return DiscoveryDiagnostic(
        status,
        code("code"),
        code("error_subcode"),
        transient if type(transient) is bool else None,
    )


class DiscoveryClient:
    def __init__(
        self, client: httpx.AsyncClient, credential: DiscoveryCredential
    ):
        self.client = client
        self.credential = credential

    async def fetch(self, username: str) -> DiscoveryResult:
        if not HANDLE.fullmatch(username):
            return DiscoveryResult("invalid_handle")
        if self.credential.expires_at <= datetime.now(timezone.utc):
            return DiscoveryResult("credentials")
        token = self.credential.token.get_secret_value()
        fields = f"business_discovery.username({username}){{{FIELDS}}}"
        response = None
        try:
            response = await self.client.get(
                f"https://graph.facebook.com/v27.0/{self.credential.business_id}",
                params={"fields": fields},
                headers={"Authorization": f"Bearer {token}"},
                timeout=20,
                follow_redirects=False,
            )
            usage = _usage(response.headers)
            body = response.json()
        except (httpx.HTTPError, ValueError):
            return DiscoveryResult(
                "network",
                diagnostic=(
                    _diagnostic(response.status_code)
                    if response is not None
                    else DiscoveryDiagnostic()
                ),
            )
        diagnostic = _diagnostic(response.status_code)
        if not isinstance(body, dict):
            return DiscoveryResult(
                "provider_error", usage_percent=usage, diagnostic=diagnostic
            )
        error = body.get("error")
        if isinstance(error, dict):
            diagnostic = _diagnostic(response.status_code, error)
            code, subcode = diagnostic.meta_code, diagnostic.meta_subcode
            if code in {4, 17, 32, 613, 80002}:
                outcome = "rate_limit"
            elif code in {10, 190, 200}:
                outcome = "credentials"
            elif code == 100 and subcode == 33:
                outcome = "unavailable"
            else:
                outcome = "invalid_request"
            return DiscoveryResult(
                outcome,
                usage_percent=usage,
                diagnostic=diagnostic,
            )
        data = body.get("business_discovery")
        profile = (
            _profile(data)
            if isinstance(data, dict) and response.is_success
            else None
        )
        return DiscoveryResult(
            "success" if profile else "provider_error",
            profile,
            usage,
            diagnostic,
        )
