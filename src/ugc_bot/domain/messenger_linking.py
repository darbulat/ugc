"""Attach-only messenger proof; canonical users and money never move."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class MaxLinkActor:
    user_id: UUID
    external_id: str


@dataclass(frozen=True)
class LinkScope:
    bot_id: int
    bot_username: str
    key_id: str
    max_bot_fingerprint: str


@dataclass(frozen=True)
class LinkContext:
    challenge_id: UUID
    owner_id: UUID
    max_id: str
    scope: LinkScope
    issued_at: datetime
    expires_at: datetime
    salt: str = field(repr=False)


@dataclass(frozen=True)
class LinkReceipt:
    command_id: UUID
    kind: str
    challenge_id: UUID | None
    state: str
    version: int
    claim_id: UUID | None = None


@dataclass(frozen=True)
class NativeLinkProposal:
    bot_id: int
    sender_id: str
    update_id: str
    message_id: str
    occurred_at: datetime
    token: str = field(repr=False)
    display_name: str
    username: str | None


@dataclass(frozen=True)
class LinkReadState:
    context: LinkContext | None
    state: str
    version: int = 0
    claim_id: UUID | None = None
    telegram_id: str | None = None
    display_name: str | None = None
    username: str | None = None
    eligible: bool = False
    verifier: str | None = None


@dataclass(frozen=True)
class LinkView:
    state: str
    challenge_id: UUID | None
    version: int
    claim_id: UUID | None
    expires_at: datetime | None
    telegram_identity: dict[str, str | None] | None
    enabled: bool
    can_create: bool
    can_confirm: bool
    can_revoke: bool
    launch_url: str | None = field(default=None, repr=False)
    receipt: LinkReceipt | None = None
