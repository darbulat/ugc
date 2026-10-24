"""Dormant immutable intent and seals; records grant no authority."""

from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from ugc_bot.domain.campaign_envelope import CampaignEnvelopeV1
from ugc_bot.domain.campaign_review import (
    CampaignDraftContent,
    CampaignSegmentV1,
)
from ugc_bot.domain.campaign_review import (
    fields as check_fields,
)
from ugc_bot.domain.campaigns import digest
from ugc_bot.domain.financial import utc


def require_uuid(value: object) -> None:
    if not isinstance(value, UUID) or not value.int:
        raise ValueError("campaign_uuid_required")


def require_positive_version(value: object) -> None:
    if type(value) is not int or value < 1:
        raise ValueError("campaign_positive_version_required")


def require_digest(value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError("campaign_digest_required")


def _identifier(value: object) -> UUID:
    if not isinstance(value, (UUID, str)):
        raise ValueError("campaign_uuid_required")
    try:
        result = UUID(str(value))
    except ValueError:
        raise ValueError("campaign_uuid_required") from None
    require_uuid(result)
    return result


def _reason(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.strip()) > 1000
    ):
        raise ValueError("campaign_reason_required")
    return value.strip()


def _base(actor_id: UUID, operation_key: str) -> None:
    require_uuid(actor_id)
    if (
        not isinstance(operation_key, str)
        or not operation_key.strip()
        or len(operation_key) > 256
    ):
        raise ValueError("campaign_operation_required")


def _parse(payload: object, names: tuple[str, ...]) -> dict[str, Any]:
    check_fields(payload, names)
    return dict(cast(dict[str, Any], payload))


def _intent_payload(value: Any, action: str) -> dict[str, Any]:
    result: dict[str, Any] = {"action": action}
    for field in fields(value):
        if field.name != "actor_id":
            item = getattr(value, field.name)
            result[field.name] = str(item) if isinstance(item, UUID) else item
    return result


@dataclass(frozen=True, slots=True)
class SubmitCampaign:
    actor_id: UUID
    operation_key: str
    campaign_id: UUID
    expected_version: int
    revision_digest: str
    policy_version: int
    terms_hash: str

    def __post_init__(self) -> None:
        _base(self.actor_id, self.operation_key)
        require_uuid(self.campaign_id)
        require_positive_version(self.expected_version)
        require_positive_version(self.policy_version)
        require_digest(self.revision_digest)
        require_digest(self.terms_hash)

    @classmethod
    def parse(cls, actor_id: UUID, payload: object) -> "SubmitCampaign":
        values = _parse(
            payload, tuple(f.name for f in fields(cls) if f.name != "actor_id")
        )
        values["campaign_id"] = _identifier(values["campaign_id"])
        return cls(actor_id=actor_id, **values)

    @property
    def payload(self) -> dict[str, Any]:
        return _intent_payload(self, "submit")

    @property
    def payload_hash(self) -> str:
        return digest(self.payload)


@dataclass(frozen=True, slots=True)
class ReviewCampaign:
    actor_id: UUID
    operation_key: str
    campaign_id: UUID
    submission_id: UUID
    expected_version: int
    revision_digest: str
    review_context: str
    decision: Literal["approve", "reject"]
    reason: str

    def __post_init__(self) -> None:
        _base(self.actor_id, self.operation_key)
        for identifier in (self.campaign_id, self.submission_id):
            require_uuid(identifier)
        require_positive_version(self.expected_version)
        require_digest(self.revision_digest)
        require_digest(self.review_context)
        if self.decision not in ("approve", "reject") or self.reason != _reason(
            self.reason
        ):
            raise ValueError("campaign_review_intent_invalid")

    @classmethod
    def parse(cls, actor_id: UUID, payload: object) -> "ReviewCampaign":
        values = _parse(
            payload, tuple(f.name for f in fields(cls) if f.name != "actor_id")
        )
        for name in ("campaign_id", "submission_id"):
            values[name] = _identifier(values[name])
        values["reason"] = _reason(values["reason"])
        return cls(actor_id=actor_id, **values)

    @property
    def payload(self) -> dict[str, Any]:
        return _intent_payload(self, self.decision)

    @property
    def payload_hash(self) -> str:
        return digest(self.payload)


@dataclass(frozen=True, slots=True)
class CancelCampaign:
    actor_id: UUID
    operation_key: str
    campaign_id: UUID
    expected_version: int
    reason: str

    def __post_init__(self) -> None:
        _base(self.actor_id, self.operation_key)
        require_uuid(self.campaign_id)
        require_positive_version(self.expected_version)
        if self.reason != _reason(self.reason):
            raise ValueError("campaign_reason_not_canonical")

    @classmethod
    def parse(cls, actor_id: UUID, payload: object) -> "CancelCampaign":
        values = _parse(
            payload, tuple(f.name for f in fields(cls) if f.name != "actor_id")
        )
        values["campaign_id"] = _identifier(values["campaign_id"])
        values["reason"] = _reason(values["reason"])
        return cls(actor_id=actor_id, **values)

    @property
    def payload(self) -> dict[str, Any]:
        return _intent_payload(self, "cancel")

    @property
    def payload_hash(self) -> str:
        return digest(self.payload)


@dataclass(frozen=True, slots=True)
class SettleCampaignExpiry:
    actor_id: UUID
    operation_key: str
    expected_policy_version: int
    reason: str

    def __post_init__(self) -> None:
        _base(self.actor_id, self.operation_key)
        require_positive_version(self.expected_policy_version)
        if self.reason != _reason(self.reason):
            raise ValueError("campaign_reason_not_canonical")

    @classmethod
    def parse(cls, actor_id: UUID, payload: object) -> "SettleCampaignExpiry":
        values = _parse(
            payload, tuple(f.name for f in fields(cls) if f.name != "actor_id")
        )
        values["reason"] = _reason(values["reason"])
        return cls(actor_id=actor_id, **values)

    @property
    def payload(self) -> dict[str, Any]:
        return _intent_payload(self, "settle_expiry")

    @property
    def payload_hash(self) -> str:
        return digest(self.payload)


@dataclass(frozen=True, slots=True)
class CampaignRevision:
    """Retain accepted draft bytes and their exact v1 hash encoding."""

    owner_id: UUID
    campaign_id: UUID
    revision_version: int
    policy_version: int
    terms_hash: str
    content: CampaignDraftContent
    segment: CampaignSegmentV1
    revision_digest: str

    def __post_init__(self) -> None:
        require_uuid(self.owner_id)
        require_uuid(self.campaign_id)
        require_positive_version(self.revision_version)
        require_positive_version(self.policy_version)
        require_digest(self.terms_hash)
        require_digest(self.revision_digest)
        if (
            not isinstance(self.content, CampaignDraftContent)
            or not isinstance(self.segment, CampaignSegmentV1)
            or self.revision_digest != digest(self.payload)
        ):
            raise ValueError("campaign_retained_revision_invalid")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "schema": "campaign-draft-v1",
            "owner_id": str(self.owner_id),
            "campaign_id": str(self.campaign_id),
            "version": self.revision_version,
            "content": self.content.payload,
            "segment": self.segment.payload,
            "policy_version": self.policy_version,
            "terms_hash": self.terms_hash,
        }


@dataclass(frozen=True, slots=True)
class CampaignLifecycleVersion:
    campaign_version: int
    revision_version: int

    def __post_init__(self) -> None:
        require_positive_version(self.campaign_version)
        require_positive_version(self.revision_version)
        if self.revision_version > self.campaign_version:
            raise ValueError("campaign_revision_version_ahead")


@dataclass(frozen=True, slots=True)
class CampaignSourceEvidence:
    """References to retained proofs, not a constructor of trusted proof."""

    source_id: UUID
    submitted_digest: str
    current_digest: str

    def __post_init__(self) -> None:
        require_uuid(self.source_id)
        require_digest(self.submitted_digest)
        require_digest(self.current_digest)

    @property
    def payload(self) -> dict[str, str]:
        return {
            "source_id": str(self.source_id),
            "submitted_digest": self.submitted_digest,
            "current_digest": self.current_digest,
        }


@dataclass(frozen=True, slots=True)
class CampaignAudience:
    sources: tuple[CampaignSourceEvidence, ...]

    def __post_init__(self) -> None:
        if type(self.sources) is not tuple or any(
            not isinstance(source, CampaignSourceEvidence)
            for source in self.sources
        ):
            raise ValueError("campaign_immutable_sources_required")
        identifiers = tuple(source.source_id for source in self.sources)
        if identifiers != tuple(sorted(set(identifiers), key=str)):
            raise ValueError("campaign_ordered_unique_sources_required")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "schema": "campaign-audience-v1",
            "sources": [s.payload for s in self.sources],
        }

    @property
    def digest(self) -> str:
        return digest(self.payload)


@dataclass(frozen=True, slots=True)
class CampaignSubmissionSeal:
    submission_id: UUID
    revision: CampaignRevision
    grant_version: int
    audience: CampaignAudience
    envelope: CampaignEnvelopeV1
    submitted_at: datetime
    review_deadline: datetime

    def __post_init__(self) -> None:
        require_uuid(self.submission_id)
        require_positive_version(self.grant_version)
        if (
            not isinstance(self.revision, CampaignRevision)
            or not isinstance(self.audience, CampaignAudience)
            or not self.audience.sources
            or any(
                s.submitted_digest != s.current_digest
                for s in self.audience.sources
            )
            or not isinstance(self.envelope, CampaignEnvelopeV1)
            or self.envelope.campaign_id != self.revision.campaign_id
            or utc(self.review_deadline) <= utc(self.submitted_at)
        ):
            raise ValueError("campaign_submission_seal_invalid")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "schema": "campaign-submission-v1",
            "submission_id": str(self.submission_id),
            "revision_digest": self.revision.revision_digest,
            "segment_digest": self.revision.segment.digest,
            "policy_version": self.revision.policy_version,
            "terms_hash": self.revision.terms_hash,
            "grant_version": self.grant_version,
            "audience": self.audience.payload,
            "envelope": self.envelope.payload,
            "envelope_digest": self.envelope.digest,
            "submitted_at": utc(self.submitted_at).isoformat(),
            "review_deadline": utc(self.review_deadline).isoformat(),
        }

    @property
    def digest(self) -> str:
        return digest(self.payload)


@dataclass(frozen=True, slots=True)
class CampaignReviewContext:
    submission: CampaignSubmissionSeal
    version: CampaignLifecycleVersion
    reviewer_id: UUID
    policy_stream_version: int
    grant_stream_version: int
    audience: CampaignAudience
    capacity_digest: str

    def __post_init__(self) -> None:
        require_uuid(self.reviewer_id)
        require_positive_version(self.policy_stream_version)
        require_positive_version(self.grant_stream_version)
        require_digest(self.capacity_digest)
        if (
            not isinstance(self.submission, CampaignSubmissionSeal)
            or not isinstance(self.version, CampaignLifecycleVersion)
            or not isinstance(self.audience, CampaignAudience)
            or self.reviewer_id == self.submission.revision.owner_id
            or self.version.revision_version
            != self.submission.revision.revision_version
        ):
            raise ValueError("campaign_review_context_invalid")
        original = {
            s.source_id: s.submitted_digest
            for s in self.submission.audience.sources
        }
        if any(
            original.get(s.source_id) != s.submitted_digest
            for s in self.audience.sources
        ):
            raise ValueError("campaign_review_source_not_submitted")

    @property
    def payload(self) -> dict[str, Any]:
        envelope = self.submission.envelope
        return {
            "schema": "campaign-review-context-v1",
            "submission_digest": self.submission.digest,
            "campaign_version": self.version.campaign_version,
            "revision_version": self.version.revision_version,
            "reviewer_id": str(self.reviewer_id),
            "policy_stream_version": self.policy_stream_version,
            "grant_stream_version": self.grant_stream_version,
            "sender_label": envelope.sender_label,
            "sender_source": envelope.sender_source,
            "template_version": envelope.template_version,
            "template_digest": envelope.template_digest,
            "default_locale": envelope.default_locale,
            "envelope_digest": envelope.digest,
            "locale_digests": envelope.payload["locale_digests"],
            "audience": self.audience.payload,
            "capacity_digest": self.capacity_digest,
        }

    @property
    def digest(self) -> str:
        return digest(self.payload)
