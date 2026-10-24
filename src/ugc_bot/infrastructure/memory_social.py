"""In-memory adapter for the same canonical-owner social link contract."""

from dataclasses import dataclass, field, replace
from uuid import UUID

from ugc_bot.application.legacy_link_ports import LegacyMemoryParticipant
from ugc_bot.application.social_ports import SocialAccountRepository
from ugc_bot.domain.social import SocialAccount


@dataclass
class InMemorySocialAccountRepository(
    SocialAccountRepository, LegacyMemoryParticipant
):
    accounts: dict[UUID, SocialAccount] = field(default_factory=dict)

    async def list_accounts(
        self,
        user_id: UUID,
        session: object | None = None,
    ) -> list[SocialAccount]:
        return [a for a in self.accounts.values() if a.user_id == user_id]

    async def get_by_id(
        self,
        account_id: UUID,
        session: object | None = None,
    ) -> SocialAccount | None:
        return self.accounts.get(account_id)

    async def save(
        self,
        account: SocialAccount,
        session: object | None = None,
    ) -> SocialAccount:
        existing = next(
            (
                a
                for a in self.accounts.values()
                if a.user_id == account.user_id
                and a.platform == account.platform
            ),
            None,
        )
        if existing is not None:
            account = replace(
                account,
                account_id=existing.account_id,
                created_at=existing.created_at,
            )
        elif account.account_id in self.accounts:
            raise ValueError("The social account owner cannot be changed")
        self.accounts[account.account_id] = account
        return account

    async def remove(
        self,
        user_id: UUID,
        account_id: UUID,
        session: object | None = None,
    ) -> bool:
        account = self.accounts.get(account_id)
        if account is None or account.user_id != user_id:
            return False
        del self.accounts[account_id]
        return True
