"""Collect supplemental links without creating extra creator identities."""

from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import TypeVar
from uuid import UUID, uuid4, uuid5

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.ports import (
    BloggerProfileRepository,
    TransactionManager,
)
from ugc_bot.application.social_ports import (
    SocialAccountRepository,
    SocialEditorFacts,
    SocialEditorRepository,
    SocialEditorSaved,
    SocialEditorState,
)
from ugc_bot.domain.entities import BloggerProfile
from ugc_bot.domain.enums import WorkFormat
from ugc_bot.domain.social import (
    SocialAccount,
    SocialPlatform,
    normalize_social_url,
)
from ugc_bot.infrastructure.db.session import with_optional_tx

T = TypeVar("T")


def instagram_account(profile: BloggerProfile) -> SocialAccount:
    """Project legacy canonical profiles without asserting unknown metrics."""
    try:
        url, handle = normalize_social_url(
            SocialPlatform.INSTAGRAM,
            profile.instagram_url,
        )
    except ValueError:
        # Historical profiles accepted handles and URLs without a scheme.
        url = profile.instagram_url
        handle = profile.instagram_username or ""
    observed = (
        profile.instagram_followers_count is not None
        and profile.instagram_stats_fetched_at is not None
    )
    return SocialAccount(
        account_id=uuid5(profile.user_id, "instagram"),
        user_id=profile.user_id,
        platform=SocialPlatform.INSTAGRAM,
        url=url,
        handle=handle,
        verified=profile.confirmed,
        external_id=profile.instagram_user_id,
        work_format=profile.work_format,
        followers_count=profile.instagram_followers_count if observed else None,
        metrics_source="legacy_profile" if observed else None,
        metrics_fetched_at=profile.instagram_stats_fetched_at
        if observed
        else None,
        created_at=profile.created_at or profile.updated_at,
        updated_at=profile.updated_at,
    )


@dataclass(slots=True)
class SocialAccountService:
    account_repo: SocialAccountRepository
    blogger_repo: BloggerProfileRepository
    transaction_manager: TransactionManager | None = None
    editor_repository: SocialEditorRepository | None = None

    def _editor(
        self,
        user_id: UUID,
        principal: AuthenticatedMessengerPrincipal,
    ) -> tuple[SocialEditorRepository, TransactionManager]:
        if (
            not isinstance(principal, AuthenticatedMessengerPrincipal)
            or principal.user_id != user_id
        ):
            raise ValueError("financial_principal_changed")
        repository = self.editor_repository
        if (
            repository is None
            or repository is not self.account_repo
            or self.transaction_manager is None
            or not callable(getattr(repository, "read_editor", None))
            or not callable(getattr(repository, "prepare_editor_write", None))
        ):
            raise ValueError("social_unavailable")
        return repository, self.transaction_manager

    @staticmethod
    def _project(
        facts: SocialEditorFacts, user_id: UUID
    ) -> tuple[SocialAccount, ...]:
        if (
            not isinstance(facts, SocialEditorFacts)
            or facts.owner_id != user_id
        ):
            raise ValueError("social_unavailable")
        return SocialAccountService._accounts(facts.profile, facts.accounts)

    @staticmethod
    def _accounts(
        profile: BloggerProfile | None,
        accounts: Collection[SocialAccount],
    ) -> tuple[SocialAccount, ...]:
        if profile is None:
            return ()
        instagram = instagram_account(profile)
        stored = next(
            (a for a in accounts if a.platform == SocialPlatform.INSTAGRAM),
            None,
        )
        if (
            stored is not None
            and instagram.verified
            and stored.external_id == instagram.external_id
        ):
            instagram = replace(
                instagram,
                verified_at=stored.verified_at,
                verification_observed_at=stored.verification_observed_at,
                verification_source=stored.verification_source,
            )
        if (
            stored is not None
            and stored.external_id == instagram.external_id
            and stored.followers_count == instagram.followers_count
            and stored.metrics_fetched_at == instagram.metrics_fetched_at
        ):
            instagram = replace(instagram, metrics_source=stored.metrics_source)
        return (
            instagram,
            *sorted(
                (a for a in accounts if a.platform != SocialPlatform.INSTAGRAM),
                key=lambda a: list(SocialPlatform).index(a.platform),
            ),
        )

    @staticmethod
    def _next(
        accounts: Collection[SocialAccount],
        *,
        skipped: Collection[SocialPlatform | str] = (),
        include_vk: bool = False,
    ) -> SocialPlatform | None:
        if not any(
            a.platform == SocialPlatform.INSTAGRAM and a.verified
            for a in accounts
        ):
            return SocialPlatform.INSTAGRAM
        present = {a.platform for a in accounts} | {
            SocialPlatform(p) for p in skipped
        }
        ordered = [
            SocialPlatform.TIKTOK,
            SocialPlatform.YOUTUBE,
            SocialPlatform.TELEGRAM,
        ]
        if include_vk:
            ordered.append(SocialPlatform.VK)
        return next((p for p in ordered if p not in present), None)

    async def editor_state(
        self,
        user_id: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal,
        skipped: Collection[SocialPlatform | str] = (),
        include_vk: bool = False,
    ) -> SocialEditorState:
        repository, transactions = self._editor(user_id, principal)
        async with transactions.transaction() as session:
            facts = await repository.read_editor(
                user_id, principal=principal, session=session
            )
            accounts = self._project(facts, user_id)
            return SocialEditorState(
                accounts,
                self._next(accounts, skipped=skipped, include_vk=include_vk),
            )

    async def save_editor_account(
        self,
        user_id: UUID,
        platform: SocialPlatform | str,
        url: str,
        *,
        principal: AuthenticatedMessengerPrincipal,
        work_format: WorkFormat | None = None,
    ) -> SocialEditorSaved:
        repository, transactions = self._editor(user_id, principal)
        async with transactions.transaction() as session:
            facts = await repository.prepare_editor_write(
                user_id, principal=principal, session=session
            )
            self._project(facts, user_id)
            if facts.profile is None:
                raise ValueError("social_creator_profile_required")
            if not facts.profile.confirmed:
                raise ValueError("social_instagram_verification_required")
            network = SocialPlatform(platform)
            if network == SocialPlatform.INSTAGRAM:
                raise ValueError("social_instagram_verification_required")
            try:
                normalized, handle = normalize_social_url(network, url)
            except ValueError:
                raise ValueError("social_profile_url_invalid") from None
            current = next(
                (a for a in facts.accounts if a.platform == network), None
            )
            saved_format = (
                current.work_format if current else facts.profile.work_format
            )
            at = datetime.now(timezone.utc)
            saved = await self.account_repo.save(
                SocialAccount(
                    account_id=uuid4(),
                    user_id=user_id,
                    platform=network,
                    url=normalized,
                    handle=handle,
                    verified=False,
                    work_format=WorkFormat(work_format)
                    if work_format is not None
                    else saved_format,
                    created_at=at,
                    updated_at=at,
                ),
                session=session,
            )
            refreshed = SocialEditorFacts(
                user_id,
                facts.profile,
                tuple(
                    await self.account_repo.list_accounts(
                        user_id, session=session
                    )
                ),
            )
            accounts = self._project(refreshed, user_id)
            if (
                not any(a == saved for a in accounts)
                or saved.platform != network
                or saved.verified
            ):
                raise ValueError("social_unavailable")
            return SocialEditorSaved(saved, self._next(accounts))

    async def remove_editor_account(
        self,
        user_id: UUID,
        account_id: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal,
    ) -> bool:
        repository, transactions = self._editor(user_id, principal)
        async with transactions.transaction() as session:
            facts = await repository.prepare_editor_write(
                user_id, principal=principal, session=session
            )
            self._project(facts, user_id)
            if account_id == uuid5(user_id, "instagram"):
                raise ValueError("social_instagram_verification_required")
            account = await self.account_repo.get_by_id(
                account_id, session=session
            )
            if account is None:
                return False
            if account.user_id != user_id:
                raise ValueError("social_account_owner_mismatch")
            if account.platform == SocialPlatform.INSTAGRAM:
                raise ValueError("social_instagram_verification_required")
            removed = await self.account_repo.remove(
                user_id, account_id, session=session
            )
            if type(removed) is not bool:
                raise ValueError("social_unavailable")
            return removed

    async def _run(
        self,
        fn: Callable[[object | None], Awaitable[T]],
        session: object | None,
    ) -> T:
        if session is not None:
            return await fn(session)
        return await with_optional_tx(self.transaction_manager, fn)

    async def list_accounts(
        self,
        user_id: UUID,
        *,
        session: object | None = None,
    ) -> list[SocialAccount]:
        async def run(db_session: object | None) -> list[SocialAccount]:
            profile = await self.blogger_repo.get_by_user_id(
                user_id,
                session=db_session,
            )
            if profile is None:
                return []
            extra = await self.account_repo.list_accounts(
                user_id, session=db_session
            )
            return list(self._accounts(profile, extra))

        return await self._run(run, session)

    async def save_account(
        self,
        user_id: UUID,
        platform: SocialPlatform | str,
        url: str,
        *,
        work_format: WorkFormat | None = None,
        session: object | None = None,
    ) -> SocialAccount:
        platform = SocialPlatform(platform)
        url, handle = normalize_social_url(platform, url)
        if platform == SocialPlatform.INSTAGRAM:
            raise ValueError("Instagram changes require verification")

        async def run(db_session: object | None) -> SocialAccount:
            profile = await self.blogger_repo.get_by_user_id(
                user_id, session=db_session
            )
            if profile is None:
                raise ValueError("A canonical creator profile is required")
            if not profile.confirmed:
                raise ValueError("Instagram verification is required")
            existing = next(
                (
                    a
                    for a in await self.account_repo.list_accounts(
                        user_id,
                        session=db_session,
                    )
                    if a.platform == platform
                ),
                None,
            )
            saved_format = (
                existing.work_format
                if existing is not None
                else profile.work_format
            )
            now = datetime.now(timezone.utc)
            return await self.account_repo.save(
                SocialAccount(
                    account_id=uuid4(),
                    user_id=user_id,
                    platform=platform,
                    url=url,
                    handle=handle,
                    verified=False,
                    work_format=WorkFormat(work_format)
                    if work_format is not None
                    else saved_format,
                    created_at=now,
                    updated_at=now,
                ),
                session=db_session,
            )

        return await self._run(run, session)

    async def remove_account(
        self,
        user_id: UUID,
        account_id: UUID,
        *,
        session: object | None = None,
    ) -> bool:
        if account_id == uuid5(user_id, "instagram"):
            raise ValueError("Instagram changes require verification")

        async def run(db_session: object | None) -> bool:
            account = await self.account_repo.get_by_id(
                account_id, session=db_session
            )
            if account is None:
                return False
            if account.user_id != user_id:
                raise ValueError("The social account owner does not match")
            if account.platform == SocialPlatform.INSTAGRAM:
                raise ValueError("Instagram changes require verification")
            return await self.account_repo.remove(
                user_id, account_id, session=db_session
            )

        return await self._run(run, session)

    async def next_platform(
        self,
        user_id: UUID,
        *,
        skipped: Collection[SocialPlatform | str] = (),
        include_vk: bool = False,
        session: object | None = None,
    ) -> SocialPlatform | None:
        accounts = await self.list_accounts(user_id, session=session)
        return self._next(accounts, skipped=skipped, include_vk=include_vk)
