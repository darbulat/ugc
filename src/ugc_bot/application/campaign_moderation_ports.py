"""Context contracts only; constructing a token authenticates no caller."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Literal, Protocol
from uuid import UUID

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.domain.campaign_capacity import (
    CampaignCapacityDelta,
    CampaignCapacityFacts,
    CampaignLimits,
    CampaignRecipientScope,
)
from ugc_bot.domain.campaign_moderation import (
    CampaignLifecycleVersion,
    CampaignReviewContext,
    CampaignRevision,
    CampaignSubmissionSeal,
    require_digest,
    require_positive_version,
    require_uuid,
)
from ugc_bot.domain.campaigns import LOCALES, digest
from ugc_bot.domain.financial import utc

CampaignPurpose = Literal["draft", "submit", "decide", "cancel", "settle"]


@dataclass(frozen=True, slots=True)
class CampaignPreflight:
    actor_id: UUID
    user_ids: tuple[UUID, ...]
    purpose: CampaignPurpose
    campaign_id: UUID | None = None
    submission_id: UUID | None = None

    def __post_init__(self) -> None:
        require_uuid(self.actor_id)
        if type(self.user_ids) is not tuple:
            raise ValueError("campaign_complete_user_scope_required")
        for identifier in self.user_ids:
            require_uuid(identifier)
        if (
            self.actor_id not in self.user_ids
            or self.user_ids != tuple(sorted(set(self.user_ids), key=str))
            or self.purpose
            not in ("draft", "submit", "decide", "cancel", "settle")
        ):
            raise ValueError("campaign_complete_user_scope_required")
        for reference in (self.campaign_id, self.submission_id):
            if reference is not None:
                require_uuid(reference)
        if (
            (
                self.purpose in ("submit", "decide", "cancel")
                and self.campaign_id is None
            )
            or (self.purpose == "decide" and self.submission_id is None)
            or (self.submission_id is not None and self.purpose != "decide")
            or (self.purpose == "settle" and self.campaign_id is not None)
        ):
            raise ValueError("campaign_preflight_references_invalid")


@dataclass(frozen=True, slots=True)
class CampaignWriteContext:
    preflight: CampaignPreflight
    owner_session: object
    root_transaction: object

    def __post_init__(self) -> None:
        if (
            not isinstance(self.preflight, CampaignPreflight)
            or self.owner_session is None
            or self.root_transaction is None
        ):
            raise ValueError("campaign_caller_transaction_required")


@dataclass(frozen=True, slots=True)
class CampaignReadContext:
    actor_id: UUID
    as_of: datetime

    def __post_init__(self) -> None:
        require_uuid(self.actor_id)
        utc(self.as_of)


def _freeze(value):
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return CampaignFrozenMap(
            tuple((key, _freeze(item)) for key, item in sorted(value.items()))
        )
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    if type(value) is float and isfinite(value):
        return value
    if (
        value is None
        or type(value) in (str, int, bool)
        or isinstance(value, (UUID, datetime))
    ):
        return value
    raise ValueError("campaign_fact_type_unavailable")


def _thaw(value):
    if isinstance(value, CampaignFrozenMap):
        return {key: _thaw(item) for key, item in value.values}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _json(value):
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return utc(value).isoformat()
    return value


@dataclass(frozen=True, slots=True)
class CampaignFrozenMap:
    values: tuple[tuple[str, object], ...]

    def __post_init__(self):
        if type(self.values) is not tuple or any(
            type(row) is not tuple
            or len(row) != 2
            or not isinstance(row[0], str)
            for row in self.values
        ):
            raise ValueError("campaign_immutable_facts_required")
        if tuple(key for key, _ in self.values) != tuple(
            sorted({key for key, _ in self.values})
        ):
            raise ValueError("campaign_immutable_facts_required")
        for _, item in self.values:
            if _freeze(_thaw(item)) != item:
                raise ValueError("campaign_immutable_facts_required")

    @classmethod
    def from_mapping(cls, values):
        if type(values) is not dict:
            raise ValueError("campaign_immutable_facts_required")
        return _freeze(values)

    @property
    def payload(self):
        return _thaw(self)

    @property
    def digest(self):
        return digest(_json(self.payload))


@dataclass(frozen=True, slots=True)
class CampaignCandidateFacts:
    facts: CampaignFrozenMap

    def __post_init__(self):
        if not isinstance(self.facts, CampaignFrozenMap):
            raise ValueError("campaign_candidate_facts_required")
        require_uuid(self.user_id)

    @classmethod
    def from_member(cls, member):
        return cls(CampaignFrozenMap.from_mapping(member))

    @property
    def member(self):
        return self.facts.payload

    @property
    def user_id(self) -> UUID:
        return self.member["context"]["actor"]["user_id"]

    @property
    def digest(self):
        return self.facts.digest

    @property
    def scope(self):
        context = self.member["context"]
        return CampaignRecipientScope(
            self.user_id,
            context["canonical_identity"],
            str(int(context["actor"]["telegram_id"])),
        )

    @property
    def source_key(self):
        member = self.member
        context, consent, receipt = (
            member["context"],
            member["consent"],
            member["receipt"],
        )
        return (
            self.user_id,
            self.scope.canonical_identity,
            self.scope.destination,
            context["inviter"]["user_id"],
            utc(context["binding_created_at"]),
            context["binding_sequence"],
            consent["version"],
            consent["operation_key"],
            receipt["result"]["consent_context"],
        )


@dataclass(frozen=True, slots=True)
class CampaignActorFacts:
    user_id: UUID
    status: str
    admin: bool
    telegram_id: str | None
    max_id: str | None

    def __post_init__(self):
        require_uuid(self.user_id)
        if (
            not isinstance(self.status, str)
            or type(self.admin) is not bool
            or any(
                value is not None and not isinstance(value, str)
                for value in (self.telegram_id, self.max_id)
            )
        ):
            raise ValueError("campaign_actor_facts_unavailable")


@dataclass(frozen=True, slots=True)
class CampaignPolicyFacts:
    stream_version: int
    publication_version: int
    enabled: bool
    terms_version: str
    terms_hash: str
    default_locale: str
    limits: CampaignLimits

    def __post_init__(self):
        require_positive_version(self.stream_version)
        require_positive_version(self.publication_version)
        require_digest(self.terms_hash)
        if (
            self.publication_version > self.stream_version
            or type(self.enabled) is not bool
            or not isinstance(self.terms_version, str)
            or not self.terms_version.strip()
            or self.default_locale not in LOCALES
            or not isinstance(self.limits, CampaignLimits)
        ):
            raise ValueError("campaign_policy_facts_unavailable")

    @classmethod
    def from_mapping(cls, row):
        return cls(
            row["version"],
            row["publication_version"],
            row["enabled"],
            row["terms_version"],
            row["terms_hash"],
            row["default_locale"],
            CampaignLimits.from_mapping(row["limits"]),
        )

    @property
    def payload(self):
        return {
            "version": self.stream_version,
            "publication_version": self.publication_version,
            "enabled": self.enabled,
            "terms_version": self.terms_version,
            "terms_hash": self.terms_hash,
            "default_locale": self.default_locale,
            "limits": self.limits.payload,
        }


@dataclass(frozen=True, slots=True)
class CampaignGrantFacts:
    owner_id: UUID
    version: int
    active: bool

    def __post_init__(self):
        require_uuid(self.owner_id)
        require_positive_version(self.version)
        if type(self.active) is not bool:
            raise ValueError("campaign_grant_facts_unavailable")


@dataclass(frozen=True, slots=True)
class CampaignAuthority:
    actor: CampaignActorFacts
    policy: CampaignPolicyFacts | None
    grant: CampaignGrantFacts | None

    def __post_init__(self):
        if (
            not isinstance(self.actor, CampaignActorFacts)
            or (
                self.policy is not None
                and not isinstance(self.policy, CampaignPolicyFacts)
            )
            or (
                self.grant is not None
                and not isinstance(self.grant, CampaignGrantFacts)
            )
        ):
            raise ValueError("campaign_authority_facts_unavailable")


@dataclass(frozen=True, slots=True)
class CampaignCapabilities:
    context: bool
    capacity: bool
    persistence: bool

    def __post_init__(self):
        if any(
            type(value) is not bool
            for value in (self.context, self.capacity, self.persistence)
        ):
            raise ValueError("campaign_capability_facts_unavailable")


@dataclass(frozen=True, slots=True)
class CampaignState:
    revision: CampaignRevision
    version: CampaignLifecycleVersion
    state: Literal[
        "draft",
        "submitted",
        "approved_waiting",
        "rejected",
        "cancelled",
        "expired",
    ]
    submission_id: UUID | None = None

    def __post_init__(self):
        if (
            not isinstance(self.revision, CampaignRevision)
            or not isinstance(self.version, CampaignLifecycleVersion)
            or self.version.revision_version != self.revision.revision_version
            or self.state
            not in (
                "draft",
                "submitted",
                "approved_waiting",
                "rejected",
                "cancelled",
                "expired",
            )
        ):
            raise ValueError("campaign_state_unavailable")
        if self.submission_id is not None:
            require_uuid(self.submission_id)

    @property
    def campaign_id(self):
        return self.revision.campaign_id

    @property
    def owner_id(self):
        return self.revision.owner_id

    @property
    def safe(self):
        return {
            "campaign_id": str(self.campaign_id),
            "version": self.version.campaign_version,
            "revision_version": self.version.revision_version,
            "revision_digest": self.revision.revision_digest,
            "state": self.state,
        }


@dataclass(frozen=True, slots=True)
class CampaignSourceFacts:
    source_id: UUID
    candidate: CampaignCandidateFacts
    eligible_at: datetime

    def __post_init__(self):
        require_uuid(self.source_id)
        if not isinstance(self.candidate, CampaignCandidateFacts):
            raise ValueError("campaign_source_facts_required")
        utc(self.eligible_at)


@dataclass(frozen=True, slots=True)
class CampaignSubmissionRecord:
    seal: CampaignSubmissionSeal
    sources: tuple[CampaignSourceFacts, ...]

    def __post_init__(self):
        if (
            not isinstance(self.seal, CampaignSubmissionSeal)
            or type(self.sources) is not tuple
            or any(
                not isinstance(row, CampaignSourceFacts) for row in self.sources
            )
        ):
            raise ValueError("campaign_submission_facts_required")
        if tuple(
            (row.source_id, row.candidate.digest) for row in self.sources
        ) != tuple(
            (row.source_id, row.submitted_digest)
            for row in self.seal.audience.sources
        ):
            raise ValueError("campaign_submission_source_mismatch")


@dataclass(frozen=True, slots=True)
class CampaignSenderSnapshot:
    label: str
    source_fingerprint: str

    def __post_init__(self):
        if any(
            not isinstance(value, str)
            or not value.strip()
            or value != value.strip()
            for value in (self.label, self.source_fingerprint)
        ):
            raise ValueError("campaign_sender_unavailable")


@dataclass(frozen=True, slots=True)
class CampaignCommandReceipt:
    actor_id: UUID
    operation_key: str
    payload_hash: str
    result: CampaignFrozenMap
    recorded_at: datetime

    def __post_init__(self):
        require_uuid(self.actor_id)
        require_digest(self.payload_hash)
        utc(self.recorded_at)
        if (
            not isinstance(self.result, CampaignFrozenMap)
            or not isinstance(self.operation_key, str)
            or not self.operation_key.strip()
            or len(self.operation_key) > 256
        ):
            raise ValueError("campaign_receipt_unavailable")


@dataclass(frozen=True, slots=True)
class CampaignDecisionFacts:
    review_id: UUID
    context: CampaignReviewContext
    decision: Literal["approve", "reject"]
    reason: str
    recorded_at: datetime
    dispatch_deadline: datetime | None

    def __post_init__(self):
        require_uuid(self.review_id)
        utc(self.recorded_at)
        if (
            not isinstance(self.context, CampaignReviewContext)
            or self.decision not in ("approve", "reject")
            or not isinstance(self.reason, str)
            or not self.reason.strip()
        ):
            raise ValueError("campaign_review_facts_unavailable")
        if (self.decision == "approve") != (self.dispatch_deadline is not None):
            raise ValueError("campaign_review_deadline_required")
        if self.dispatch_deadline is not None and utc(
            self.dispatch_deadline
        ) <= utc(self.recorded_at):
            raise ValueError("campaign_review_deadline_required")


@dataclass(frozen=True, slots=True)
class CampaignDeliveryJob:
    job_id: UUID
    campaign_id: UUID
    submission_id: UUID
    review_id: UUID
    source_id: UUID
    revision_digest: str
    audience_digest: str
    envelope_digest: str
    publication_version: int
    dispatch_deadline: datetime

    def __post_init__(self):
        for identifier in (
            self.job_id,
            self.campaign_id,
            self.submission_id,
            self.review_id,
            self.source_id,
        ):
            require_uuid(identifier)
        for value in (
            self.revision_digest,
            self.audience_digest,
            self.envelope_digest,
        ):
            require_digest(value)
        require_positive_version(self.publication_version)
        utc(self.dispatch_deadline)


@dataclass(frozen=True, slots=True)
class CampaignExpiryItem:
    state: CampaignState
    reservation_ids: tuple[UUID, ...]
    terminal: bool
    deadline: datetime
    reason: str

    def __post_init__(self):
        if (
            not isinstance(self.state, CampaignState)
            or type(self.reservation_ids) is not tuple
            or type(self.terminal) is not bool
            or not isinstance(self.reason, str)
            or not self.reason.strip()
        ):
            raise ValueError("campaign_expiry_facts_unavailable")
        for identifier in self.reservation_ids:
            require_uuid(identifier)
        utc(self.deadline)


@dataclass(frozen=True, slots=True)
class CampaignExpiryBatch:
    items: tuple[CampaignExpiryItem, ...]
    has_more: bool

    def __post_init__(self):
        if (
            type(self.items) is not tuple
            or any(
                not isinstance(row, CampaignExpiryItem) for row in self.items
            )
            or type(self.has_more) is not bool
        ):
            raise ValueError("campaign_expiry_facts_unavailable")


@dataclass(frozen=True, slots=True)
class CampaignSettlement:
    states: tuple[CampaignState, ...]
    capacity: CampaignCapacityDelta

    def __post_init__(self):
        if (
            type(self.states) is not tuple
            or any(not isinstance(row, CampaignState) for row in self.states)
            or not isinstance(self.capacity, CampaignCapacityDelta)
        ):
            raise ValueError("campaign_immutable_settlement_required")


@dataclass(frozen=True, slots=True)
class CampaignMutation:
    states: tuple[CampaignState, ...]
    submissions: tuple[CampaignSubmissionRecord, ...]
    decisions: tuple[CampaignDecisionFacts, ...]
    jobs: tuple[CampaignDeliveryJob, ...]
    capacity: CampaignCapacityDelta
    receipt: CampaignCommandReceipt

    def __post_init__(self):
        for rows, cls in (
            (self.states, CampaignState),
            (self.submissions, CampaignSubmissionRecord),
            (self.decisions, CampaignDecisionFacts),
            (self.jobs, CampaignDeliveryJob),
        ):
            if type(rows) is not tuple or any(
                not isinstance(row, cls) for row in rows
            ):
                raise ValueError("campaign_immutable_mutation_required")
        if not isinstance(
            self.capacity, CampaignCapacityDelta
        ) or not isinstance(self.receipt, CampaignCommandReceipt):
            raise ValueError("campaign_immutable_mutation_required")


class CampaignModerationRepository(Protocol):
    """Future adapters must enforce actual barriers and receipt-first admission.

    Preflight is provisional. Prepare uses the complete sorted User → history
    → campaign barriers. Native/action authority and retained receipt resolution
    precede every private new-admission refusal. These declarations implement no
    lock, snapshot, SQL, replay, capacity or persistence behavior.
    """

    async def preflight(
        self,
        actor_id: UUID,
        campaign_id: UUID | None,
        submission_id: UUID | None,
        *,
        purpose: CampaignPurpose,
        session: object,
    ) -> CampaignPreflight: ...

    async def prepare(
        self,
        preflight: CampaignPreflight,
        *,
        principal: AuthenticatedMessengerPrincipal | None,
        session: object,
    ) -> CampaignWriteContext: ...

    async def begin_read(
        self,
        actor_id: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal | None,
        session: object,
    ) -> CampaignReadContext: ...

    async def capabilities(
        self, *, session: object
    ) -> CampaignCapabilities: ...
    async def authority(
        self,
        actor_id: UUID,
        *,
        context: CampaignReadContext | CampaignWriteContext,
        session: object,
    ) -> CampaignAuthority: ...
    async def command(
        self,
        actor_id: UUID,
        operation_key: str,
        *,
        context: CampaignWriteContext,
        session: object,
    ) -> CampaignCommandReceipt | None: ...
    async def state(
        self,
        campaign_id: UUID,
        *,
        context: CampaignReadContext | CampaignWriteContext,
        session: object,
    ) -> CampaignState | None: ...
    async def candidates(
        self,
        owner_id: UUID,
        *,
        context: CampaignReadContext | CampaignWriteContext,
        session: object,
    ) -> tuple[CampaignCandidateFacts, ...]: ...
    async def publisher(
        self,
        owner_id: UUID,
        *,
        context: CampaignReadContext | CampaignWriteContext,
        session: object,
    ) -> CampaignGrantFacts | None: ...
    async def sender_snapshot(
        self, owner_id: UUID, *, context: CampaignWriteContext, session: object
    ) -> CampaignSenderSnapshot: ...
    async def submission(
        self,
        submission_id: UUID,
        *,
        context: CampaignReadContext | CampaignWriteContext,
        session: object,
    ) -> CampaignSubmissionRecord | None: ...
    async def capacity_facts(
        self,
        owner_id: UUID,
        recipients: tuple[CampaignRecipientScope, ...],
        *,
        at: datetime,
        context: CampaignReadContext | CampaignWriteContext,
        session: object,
    ) -> CampaignCapacityFacts: ...
    async def due(
        self,
        *,
        at: datetime,
        limit: int,
        context: CampaignWriteContext,
        session: object,
    ) -> CampaignExpiryBatch: ...
    async def review_page(
        self, page: int, *, context: CampaignReadContext, session: object
    ) -> tuple[CampaignSubmissionRecord, ...]: ...
    async def apply(
        self,
        write: CampaignMutation,
        *,
        context: CampaignWriteContext,
        session: object,
    ) -> None: ...
