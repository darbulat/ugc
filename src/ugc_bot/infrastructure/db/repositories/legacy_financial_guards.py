"""Shared legacy payout safety-stop enforced by persistence entry points.

The existing user row is the common serialization lock. It deliberately locks
more strictly than a currency-only mutex, so absent guard rows cannot race an
ISSUE. All affected users are locked in deterministic UUID order. No network or
bank call belongs inside these transactions.
"""

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, union
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ugc_bot.application.errors import LegacyPayoutBlockedError
from ugc_bot.application.ports import LegacyFinancialGuardRepository
from ugc_bot.domain.entities import Interaction
from ugc_bot.domain.enums import InteractionStatus
from ugc_bot.infrastructure.db.models import (
    InteractionModel,
    LegacyFinancialCaseEventModel,
    LegacyFinancialCaseModel,
    LegacyFinancialGuardModel,
    OrderModel,
    ReferralIncomeEntryModel,
    UserModel,
    UserReferralBindingModel,
)
from ugc_bot.infrastructure.db.repositories._shared import _resolve_session


@dataclass(slots=True)
class SqlAlchemyLegacyFinancialGuardRepository(LegacyFinancialGuardRepository):
    session_factory: async_sessionmaker[AsyncSession]

    async def block_for_interaction(
        self,
        interaction: Interaction,
        session: object | None = None,
        *,
        reopen: bool = False,
    ) -> None:
        async with _resolve_session(self.session_factory, session) as db:
            created = await db.scalar(
                insert(LegacyFinancialCaseModel)
                .values(
                    interaction_id=interaction.interaction_id,
                    source="legacy_interaction",
                    cause="feedback_issue",
                )
                .on_conflict_do_nothing()
                .returning(LegacyFinancialCaseModel.interaction_id)
            )
            if created is not None:
                db.add(
                    LegacyFinancialCaseEventModel(
                        event_id=uuid4(),
                        interaction_id=interaction.interaction_id,
                        version=1,
                        actor_id=None,
                        decision="opened",
                        reason="feedback_issue",
                        details={
                            "from_blogger": interaction.from_blogger,
                            "from_advertiser": interaction.from_advertiser,
                        },
                    )
                )
                await db.flush()
            if created is None and reopen:
                case = await db.get(
                    LegacyFinancialCaseModel, interaction.interaction_id
                )
                if case is not None:
                    decision = "reopened" if case.released else "source_updated"
                    case.released = False
                    case.version += 1
                    db.add(
                        LegacyFinancialCaseEventModel(
                            event_id=uuid4(),
                            interaction_id=interaction.interaction_id,
                            version=case.version,
                            actor_id=None,
                            decision=decision,
                            reason="new_feedback_issue",
                            details={
                                "from_blogger": interaction.from_blogger,
                                "from_advertiser": interaction.from_advertiser,
                            },
                        )
                    )
                    await db.flush()
            # Include both current bindings and historically accrued recipients;
            # a later profile change must not let an old beneficiary escape.
            bindings = (
                select(
                    UserReferralBindingModel.referrer_user_id,
                    OrderModel.currency,
                )
                .select_from(UserReferralBindingModel)
                .join(OrderModel, OrderModel.order_id == interaction.order_id)
                .where(
                    UserReferralBindingModel.referred_user_id.in_(
                        [interaction.blogger_id, interaction.advertiser_id]
                    )
                )
            )
            historical = select(
                ReferralIncomeEntryModel.referrer_user_id,
                ReferralIncomeEntryModel.currency,
            ).where(ReferralIncomeEntryModel.order_id == interaction.order_id)
            pairs = (await db.execute(union(bindings, historical))).all()
            recipients = sorted({row[0] for row in pairs}, key=str)
            if not recipients:
                return
            # PG NO KEY UPDATE serializes wallets without conflicting with
            # the complaint/actor FK KEY SHARE locks already held by callers.
            await db.execute(
                select(UserModel.user_id)
                .where(UserModel.user_id.in_(recipients))
                .order_by(UserModel.user_id)
                .with_for_update(key_share=True)
            )
            for user_id, currency in pairs:
                await db.execute(
                    insert(LegacyFinancialGuardModel)
                    .values(
                        user_id=user_id,
                        currency=currency,
                        interaction_id=interaction.interaction_id,
                    )
                    .on_conflict_do_nothing()
                )

    async def assert_payout_allowed(
        self, user_id: UUID, currency: str, session: object | None = None
    ) -> None:
        async with _resolve_session(self.session_factory, session) as db:
            await db.execute(
                select(UserModel.user_id)
                .where(UserModel.user_id == user_id)
                .with_for_update(key_share=True)
            )
            blocked = await db.scalar(
                select(LegacyFinancialGuardModel.interaction_id)
                .where(
                    LegacyFinancialGuardModel.user_id == user_id,
                    LegacyFinancialGuardModel.currency == currency,
                    ~select(LegacyFinancialCaseModel.interaction_id)
                    .where(
                        LegacyFinancialCaseModel.interaction_id
                        == LegacyFinancialGuardModel.interaction_id,
                        LegacyFinancialCaseModel.released.is_(True),
                    )
                    .exists(),
                )
                .limit(1)
            )
            # Also cover issues predating this additive guard migration and
            # bindings that appeared after the original issue was recorded.
            bindings = (
                select(InteractionModel.interaction_id)
                .join(
                    OrderModel, OrderModel.order_id == InteractionModel.order_id
                )
                .join(
                    UserReferralBindingModel,
                    or_(
                        UserReferralBindingModel.referred_user_id
                        == InteractionModel.blogger_id,
                        UserReferralBindingModel.referred_user_id
                        == InteractionModel.advertiser_id,
                    ),
                )
                .where(
                    InteractionModel.status == InteractionStatus.ISSUE,
                    UserReferralBindingModel.referrer_user_id == user_id,
                    OrderModel.currency == currency,
                )
            )
            historical = (
                select(InteractionModel.interaction_id)
                .join(
                    ReferralIncomeEntryModel,
                    and_(
                        ReferralIncomeEntryModel.order_id
                        == InteractionModel.order_id,
                        ReferralIncomeEntryModel.referrer_user_id == user_id,
                        ReferralIncomeEntryModel.currency == currency,
                    ),
                )
                .where(InteractionModel.status == InteractionStatus.ISSUE)
            )
            unreviewed = (
                ~select(LegacyFinancialCaseModel.interaction_id)
                .where(
                    LegacyFinancialCaseModel.interaction_id
                    == InteractionModel.interaction_id,
                    LegacyFinancialCaseModel.released.is_(True),
                )
                .exists()
            )
            live_issue = await db.scalar(
                union(
                    bindings.where(unreviewed), historical.where(unreviewed)
                ).limit(1)
            )
            if blocked is not None or live_issue is not None:
                raise LegacyPayoutBlockedError(
                    "Legacy payout blocked pending dispute review."
                )
