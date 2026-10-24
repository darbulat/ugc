"""Explicit synthetic editor authority/UOW; no SQL or MVCC evidence."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from uuid import UUID

from tests.helpers.factories import (
    create_test_blogger_profile,
    create_test_user,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
    require_current_principal,
)
from ugc_bot.application.services.social_account_service import (
    SocialAccountService,
)
from ugc_bot.application.social_ports import SocialAccountRepository
from ugc_bot.domain.social import SocialAccount
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryUserRepository,
)
from ugc_bot.infrastructure.memory_social import InMemorySocialAccountRepository


@dataclass
class EditorSession:
    owner: object
    active: bool = True


@dataclass
class MemorySocialEditor(SocialAccountRepository):
    """One wrapper supplies BOTH interfaces over real memory storage."""

    users: InMemoryUserRepository
    profiles: InMemoryBloggerProfileRepository
    storage: InMemorySocialAccountRepository = field(
        default_factory=InMemorySocialAccountRepository
    )
    events: list[str] = field(default_factory=list)
    starts: int = 0
    commits: int = 0
    rollbacks: int = 0
    failure: BaseException | None = None
    fail_post_save: bool = False
    wrong_facts: bool = False
    saved: bool = False

    def service(self) -> SocialAccountService:
        return SocialAccountService(
            self, self.profiles, self, editor_repository=self
        )

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[EditorSession]:
        previous = deepcopy(self.storage.accounts)
        session = EditorSession(self)
        self.starts += 1
        self.events.append("begin")
        self.saved = False
        try:
            yield session
        except BaseException:
            self.storage.accounts = previous
            self.rollbacks += 1
            self.events.append("rollback")
            raise
        else:
            self.commits += 1
            self.events.append("commit")
        finally:
            session.active = False

    def _session(self, session: object) -> None:
        if (
            not isinstance(session, EditorSession)
            or not session.active
            or session.owner is not self
        ):
            raise ValueError("social_unavailable")

    async def _facts(self, user_id, principal, session):
        from ugc_bot.application.social_ports import SocialEditorFacts

        self._session(session)
        self.events.append("authority")
        user = await self.users.get_by_id(user_id)
        require_current_principal(
            principal,
            user_id,
            user.user_id if user else None,
            user.telegram_id if user else None,
            user.max_id if user else None,
        )
        if user is None or user.status in {"blocked", "bot_blocked", "deleted"}:
            raise ValueError("social_account_unavailable")
        if self.failure is not None:
            raise self.failure
        self.events.append("facts")
        profile = await self.profiles.get_by_user_id(user_id)
        accounts = tuple(await self.storage.list_accounts(user_id))
        owner = UUID(int=999) if self.wrong_facts else user_id
        return SocialEditorFacts(owner, deepcopy(profile), deepcopy(accounts))

    async def read_editor(self, user_id, *, principal, session):
        self.events.append("read")
        return await self._facts(user_id, principal, session)

    async def prepare_editor_write(self, user_id, *, principal, session):
        self.events.append("prepare")
        return await self._facts(user_id, principal, session)

    async def list_accounts(self, user_id, session=None):
        if session is not None:
            self._session(session)
        self.events.append("list")
        if self.saved and self.fail_post_save:
            raise RuntimeError("PRIVATE post-save source failure")
        return await self.storage.list_accounts(user_id)

    async def get_by_id(self, account_id, session=None):
        if session is not None:
            self._session(session)
        self.events.append("get")
        return await self.storage.get_by_id(account_id)

    async def save(self, account: SocialAccount, session=None):
        if session is not None:
            self._session(session)
        self.events.append("save")
        self.saved = True
        return await self.storage.save(account)

    async def remove(self, user_id, account_id, session=None):
        if session is not None:
            self._session(session)
        self.events.append("remove")
        return await self.storage.remove(user_id, account_id)


async def editor_fixture(*, confirmed=True, profile=True, platform="telegram"):
    users = InMemoryUserRepository()
    profiles = InMemoryBloggerProfileRepository()
    user = await create_test_user(
        users, external_id="101", telegram_id="101", max_id="202"
    )
    if profile:
        await create_test_blogger_profile(
            profiles, user.user_id, confirmed=confirmed
        )
    editor = MemorySocialEditor(users, profiles)
    principal = AuthenticatedMessengerPrincipal(
        user.user_id, platform, "101" if platform == "telegram" else "202"
    )
    return editor, user, principal
