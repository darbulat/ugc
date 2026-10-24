"""Bounded preparation facts for legacy Instagram/MAX attachment."""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from ugc_bot.domain.entities import User

AttachmentState = Literal["ready", "same_account", "conflict", "unavailable"]


def validated_max_chat_id(value: str | None) -> str | None:
    return (
        value
        if isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value)
        else None
    )


class LegacySqlParticipant:
    """Explicit SQL adapter opt-in to the caller transaction contract."""


class LegacyMemoryParticipant:
    """Explicit adapter opt-in; SQL and unknown adapters never participate."""


class LegacyMemoryTransaction(ABC):
    """Explicit supported memory caller transaction."""

    @property
    @abstractmethod
    def active(self) -> bool: ...

    @abstractmethod
    def contains(self, repository: LegacyMemoryParticipant) -> bool: ...


@dataclass(frozen=True, slots=True)
class LegacyMaxPreparation:
    target_id: UUID
    code_id: UUID | None
    max_id: str | None
    max_chat_id: str | None
    user_ids: tuple[UUID, ...] = ()
    state: AttachmentState = "unavailable"
    reason: str = "preparation_unavailable"
    locale: str = "ru"
    session: object | None = None

    @property
    def protected(self) -> bool:
        return self.target_id in self.user_ids and self.session is not None


@dataclass(frozen=True, slots=True)
class LegacyMaxAttachment:
    state: AttachmentState
    reason: str = ""
    user: User | None = None


def attachment_state(
    target: User | None, owner: User | None, max_id: str | None
) -> tuple[AttachmentState, str]:
    if target is None:
        return "unavailable", "target_missing"
    if max_id is None:
        return "ready", ""
    if not isinstance(max_id, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{1,128}", max_id
    ):
        return "unavailable", "native_identity_invalid"
    if target.max_id == max_id and (
        owner is None or owner.user_id == target.user_id
    ):
        return "same_account", ""
    if target.max_id is not None:
        return "conflict", "target_bound_elsewhere"
    if owner is not None and owner.user_id != target.user_id:
        return "conflict", "separate_canonical_owner"
    return "ready", ""
