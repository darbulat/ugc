"""Typed persistence and application boundaries for creator social links."""

from abc import ABC, abstractmethod
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.domain.entities import BloggerProfile
from ugc_bot.domain.enums import WorkFormat
from ugc_bot.domain.social import SocialAccount, SocialPlatform


class SocialAccountRepository(ABC):
    @abstractmethod
    async def list_accounts(
        self,
        user_id: UUID,
        session: object | None = None,
    ) -> list[SocialAccount]: ...

    @abstractmethod
    async def get_by_id(
        self,
        account_id: UUID,
        session: object | None = None,
    ) -> SocialAccount | None: ...

    @abstractmethod
    async def save(
        self,
        account: SocialAccount,
        session: object | None = None,
    ) -> SocialAccount: ...

    @abstractmethod
    async def remove(
        self,
        user_id: UUID,
        account_id: UUID,
        session: object | None = None,
    ) -> bool: ...


class SocialAccountPort(Protocol):
    """Caller user_id must always come from the authenticated principal."""

    async def list_accounts(
        self,
        user_id: UUID,
        *,
        session: object | None = None,
    ) -> list[SocialAccount]: ...

    async def save_account(
        self,
        user_id: UUID,
        platform: SocialPlatform | str,
        url: str,
        *,
        work_format: WorkFormat | None = None,
        session: object | None = None,
    ) -> SocialAccount: ...

    async def remove_account(
        self,
        user_id: UUID,
        account_id: UUID,
        *,
        session: object | None = None,
    ) -> bool: ...

    async def next_platform(
        self,
        user_id: UUID,
        *,
        skipped: Collection[SocialPlatform | str] = (),
        include_vk: bool = False,
        session: object | None = None,
    ) -> SocialPlatform | None: ...


def _validate_editor_accounts(accounts: tuple[SocialAccount, ...]) -> None:
    if type(accounts) is not tuple:
        raise ValueError("social_unavailable")
    for account in accounts:
        if not isinstance(account, SocialAccount):
            raise ValueError("social_unavailable")
        required = (
            isinstance(account.account_id, UUID)
            and bool(account.account_id.int),
            isinstance(account.user_id, UUID) and bool(account.user_id.int),
            isinstance(account.platform, SocialPlatform),
            isinstance(account.work_format, WorkFormat),
            type(account.verified) is bool,
            type(account.url) is str,
            type(account.handle) is str,
            isinstance(account.created_at, datetime),
            isinstance(account.updated_at, datetime),
            account.followers_count is None
            or (
                type(account.followers_count) is int
                and account.followers_count >= 0
            ),
        )
        strings = (
            account.external_id,
            account.metrics_source,
            account.verification_source,
        )
        dates = (
            account.metrics_fetched_at,
            account.verified_at,
            account.verification_observed_at,
        )
        if (
            not all(required)
            or any(
                value is not None and type(value) is not str
                for value in strings
            )
            or any(
                value is not None and not isinstance(value, datetime)
                for value in dates
            )
        ):
            raise ValueError("social_unavailable")


def _validate_next(platform: SocialPlatform | None) -> None:
    if platform is not None and not isinstance(platform, SocialPlatform):
        raise ValueError("social_unavailable")


@dataclass(frozen=True, slots=True)
class SocialEditorFacts:
    owner_id: UUID
    profile: BloggerProfile | None
    accounts: tuple[SocialAccount, ...]

    def __post_init__(self):
        _validate_editor_accounts(self.accounts)
        if (
            not isinstance(self.owner_id, UUID)
            or not self.owner_id.int
            or (
                self.profile is not None
                and (
                    not isinstance(self.profile, BloggerProfile)
                    or self.profile.user_id != self.owner_id
                )
            )
            or any(a.user_id != self.owner_id for a in self.accounts)
            or len({a.platform for a in self.accounts}) != len(self.accounts)
        ):
            raise ValueError("social_unavailable")


@dataclass(frozen=True, slots=True)
class SocialEditorState:
    accounts: tuple[SocialAccount, ...]
    next_platform: SocialPlatform | None

    def __post_init__(self):
        _validate_editor_accounts(self.accounts)
        _validate_next(self.next_platform)


@dataclass(frozen=True, slots=True)
class SocialEditorSaved:
    account: SocialAccount
    next_platform: SocialPlatform | None

    def __post_init__(self):
        _validate_editor_accounts((self.account,))
        _validate_next(self.next_platform)


class SocialEditorRepository(Protocol):
    async def read_editor(
        self,
        user_id: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal,
        session: object,
    ) -> SocialEditorFacts: ...

    async def prepare_editor_write(
        self,
        user_id: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal,
        session: object,
    ) -> SocialEditorFacts: ...


class SocialEditorPort(Protocol):
    async def editor_state(
        self,
        user_id: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal,
        skipped: Collection[SocialPlatform | str] = (),
        include_vk: bool = False,
    ) -> SocialEditorState: ...

    async def save_editor_account(
        self,
        user_id: UUID,
        platform: SocialPlatform | str,
        url: str,
        *,
        principal: AuthenticatedMessengerPrincipal,
        work_format: WorkFormat | None = None,
    ) -> SocialEditorSaved: ...

    async def remove_editor_account(
        self,
        user_id: UUID,
        account_id: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal,
    ) -> bool: ...
