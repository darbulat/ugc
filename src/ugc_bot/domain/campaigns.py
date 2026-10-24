"""Explicit configuration intent without inferred consent or authority."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

Action = Literal[
    "publish", "suspend", "grant", "revoke", "consent", "unsubscribe"
]
LOCALES = frozenset(("ru", "en", "kk", "be", "uz"))
LIMIT_NAMES = (
    "recipients_per_campaign",
    "submissions_per_owner",
    "active_per_owner",
    "attempts_per_owner",
    "attempts_global",
    "attempts_per_recipient",
    "window_seconds",
    "recipient_cooldown_seconds",
    "title_max_chars",
    "text_max_chars",
    "link_max_chars",
    "review_ttl_seconds",
    "dispatch_ttl_seconds",
    "claim_batch_size",
    "worker_concurrency",
    "starts_per_second",
    "metrics_max_age_seconds",
)
FIELDS = {
    "publish": {"terms_version", "default_locale", "terms", "limits", "reason"},
    "suspend": {"reason"},
    "grant": {"owner_id", "reason"},
    "revoke": {"owner_id", "reason"},
    "consent": {"policy_version", "terms_hash", "consent_context"},
    "unsubscribe": set(),
}


def canonical(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def terms_hash(terms: dict[str, str], default_locale: str) -> str:
    return digest({"terms": terms, "default_locale": default_locale})


def publication(payload: dict[str, Any]) -> dict[str, Any]:
    terms = payload["terms"]
    limits = payload["limits"]
    if (
        not isinstance(terms, dict)
        or not terms
        or set(terms) - LOCALES
        or any(
            not isinstance(v, str) or not v.strip() or len(v) > 30000
            for v in terms.values()
        )
    ):
        raise ValueError("campaign_full_terms_required")
    if payload["default_locale"] not in terms:
        raise ValueError("campaign_default_terms_required")
    if (
        not isinstance(limits, dict)
        or set(limits) != set(LIMIT_NAMES)
        or any(
            type(v) is not int or not 0 < v <= 2147483647
            for v in limits.values()
        )
    ):
        raise ValueError("campaign_all_positive_limits_required")
    return {
        **payload,
        "terms_hash": terms_hash(terms, payload["default_locale"]),
    }


@dataclass(frozen=True)
class CampaignCommand:
    actor_id: UUID
    operation_key: str
    action: Action
    expected_version: int
    payload: dict[str, Any]

    def __post_init__(self):
        if not isinstance(self.actor_id, UUID) or not self.actor_id.int:
            raise ValueError("campaign_actor_required")
        if (
            not isinstance(self.operation_key, str)
            or not self.operation_key.strip()
            or len(self.operation_key) > 256
        ):
            raise ValueError("campaign_operation_required")
        if (
            self.action not in FIELDS
            or set(self.payload) != FIELDS[self.action]
        ):
            raise ValueError("campaign_unexpected_fields")
        if type(self.expected_version) is not int or self.expected_version < 0:
            raise ValueError("campaign_expected_version_required")
        for key in ("reason", "terms_version"):
            if key in self.payload and (
                not isinstance(self.payload[key], str)
                or not self.payload[key].strip()
                or len(self.payload[key]) > 1000
            ):
                raise ValueError("campaign_provenance_required")
        if self.action == "publish":
            publication(self.payload)
        self._validate_references()

    def _validate_references(self):
        if (
            self.action in ("grant", "revoke")
            and not UUID(str(self.payload["owner_id"])).int
        ):
            raise ValueError("campaign_owner_required")
        if self.action == "consent" and (
            type(self.payload["policy_version"]) is not int
            or self.payload["policy_version"] < 1
            or not isinstance(self.payload["terms_hash"], str)
            or len(self.payload["terms_hash"]) != 64
            or not isinstance(self.payload["consent_context"], str)
            or len(self.payload["consent_context"]) != 64
        ):
            raise ValueError("campaign_terms_reference_required")

    @property
    def payload_hash(self):
        return digest(
            {
                "action": self.action,
                "expected_version": self.expected_version,
                "payload": self.payload,
            }
        )


class CampaignConflict(ValueError):
    """Refresh current state; never silently replay intent at a new version."""
