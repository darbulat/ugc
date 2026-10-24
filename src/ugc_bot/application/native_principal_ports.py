"""Trusted request identity, kept outside financial commands and receipts."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

NativePlatform = Literal["telegram", "max"]


@dataclass(frozen=True, slots=True)
class AuthenticatedMessengerPrincipal:
    """Server-resolved signed identity; revalidate at the existing User lock."""

    user_id: UUID
    platform: NativePlatform
    external_id: str

    def __post_init__(self):
        if (
            not isinstance(self.user_id, UUID)
            or not self.user_id.int
            or self.platform not in ("telegram", "max")
            or not isinstance(self.external_id, str)
            or not self.external_id
            or len(self.external_id) > 128
        ):
            raise ValueError("financial_principal_invalid")


def require_current_principal(
    principal: AuthenticatedMessengerPrincipal | None,
    actor_id: UUID,
    current_id: UUID | None,
    telegram_id: str | None,
    max_id: str | None,
) -> None:
    """Optional for trusted internal callers; HTTP always supplies proof."""
    if principal is None:
        return
    if (
        not isinstance(principal, AuthenticatedMessengerPrincipal)
        or principal.user_id != actor_id
        or current_id != actor_id
        or (telegram_id if principal.platform == "telegram" else max_id)
        != principal.external_id
    ):
        raise ValueError("financial_principal_changed")
