"""Legacy review persistence. Lock order: interaction -> sorted wallet users.

No income, payout, reserve, or interaction status writes belong to review.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ugc_bot.domain.enums import PayoutRequestStatus, UserStatus
from ugc_bot.infrastructure.db.models import (
    InteractionModel,
    LegacyFinancialCaseEventModel,
    LegacyFinancialCaseModel,
    LegacyFinancialGuardModel,
    OrderModel,
    PayoutRequestModel,
    ReferralIncomeEntryModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.legacy_financial_guards import (
    SqlAlchemyLegacyFinancialGuardRepository as GuardRepository,
)


@dataclass
class SqlAlchemyLegacyFinancialCaseRepository:
    session_factory: async_sessionmaker[AsyncSession]

    async def _authorize(self, db: AsyncSession, actor_id: UUID) -> None:
        admin = await db.scalar(
            select(UserModel.admin).where(
                UserModel.user_id == actor_id,
                UserModel.status.notin_(
                    (UserStatus.BLOCKED, UserStatus.DELETED)
                ),
            )
        )
        if admin is not True:
            raise PermissionError("Financial review requires an actual admin")

    async def review(
        self,
        interaction_id: UUID,
        *,
        actor_id: UUID,
        expected_version: int,
        command_id: UUID,
        decision: str,
        reason: str,
        confirmed_result: bool,
    ) -> dict[str, Any]:
        async with self.session_factory.begin() as db:
            # Same order as ISSUE persistence: never lock user -> interaction.
            interaction = await db.scalar(
                select(InteractionModel)
                .where(InteractionModel.interaction_id == interaction_id)
                .with_for_update()
            )
            if interaction is None:
                raise ValueError("Legacy interaction not found")
            guards = list(
                (
                    await db.scalars(
                        select(LegacyFinancialGuardModel).where(
                            LegacyFinancialGuardModel.interaction_id
                            == interaction_id
                        )
                    )
                ).all()
            )
            recipients = sorted({g.user_id for g in guards}, key=str)
            if recipients:
                await db.execute(
                    select(UserModel.user_id)
                    .where(UserModel.user_id.in_(recipients))
                    .order_by(UserModel.user_id)
                    .with_for_update(key_share=True)
                )
            await self._authorize(db, actor_id)
            case = await db.get(LegacyFinancialCaseModel, interaction_id)
            if case is None:
                raise ValueError(
                    "Legacy case not found; record old ISSUE first"
                )
            previous = await db.scalar(
                select(LegacyFinancialCaseEventModel).where(
                    LegacyFinancialCaseEventModel.command_id == command_id
                )
            )
            details = {
                "confirmed_result": confirmed_result,
                "expected_version": expected_version,
            }
            if previous is not None:
                if (
                    previous.interaction_id,
                    previous.actor_id,
                    previous.decision,
                    previous.reason,
                    previous.details,
                ) != (interaction_id, actor_id, decision, reason, details):
                    raise ValueError("Command id reused with different review")
                return {
                    "interaction_id": str(interaction_id),
                    "version": previous.version,
                    "released": decision == "release_no_adjustment",
                }
            if expected_version != case.version:
                raise ValueError("Stale legacy case version")
            if not reason.strip() or decision not in {
                "release_no_adjustment",
                "keep_blocked",
            }:
                raise ValueError(
                    "Explicit financial decision and reason required"
                )
            if case.released:
                raise ValueError("Legacy case already released")
            if decision == "release_no_adjustment":
                self._require_confirmation(confirmed_result)
                await self._validate_basis(db, interaction.order_id, guards)
                case.released = True
            case.version += 1
            db.add(
                LegacyFinancialCaseEventModel(
                    event_id=uuid4(),
                    interaction_id=interaction_id,
                    version=case.version,
                    actor_id=actor_id,
                    command_id=command_id,
                    decision=decision,
                    reason=reason,
                    details=details,
                )
            )
            return {
                "interaction_id": str(interaction_id),
                "version": case.version,
                "released": case.released,
            }

    @staticmethod
    def _require_confirmation(confirmed_result: bool) -> None:
        if not confirmed_result:
            raise ValueError("Confirmed legacy result required")

    async def _validate_basis(
        self,
        db: AsyncSession,
        order_id: UUID,
        guards: list[LegacyFinancialGuardModel],
    ) -> None:
        order = await db.get(OrderModel, order_id)
        if (
            order is None
            or not self._money(order.price)
            or order.price <= 0
            or not guards
        ):
            raise ValueError(
                "Unknown legacy money basis; financial correction required"
            )
        for guard in guards:
            income = list(
                (
                    await db.scalars(
                        select(ReferralIncomeEntryModel).where(
                            ReferralIncomeEntryModel.referrer_user_id
                            == guard.user_id,
                            ReferralIncomeEntryModel.currency == guard.currency,
                        )
                    )
                ).all()
            )
            if not any(row.order_id == order_id for row in income):
                raise ValueError(
                    "Unknown legacy money basis; financial correction required"
                )
            for row in income:
                if (
                    not all(
                        self._money(value)
                        for value in (
                            row.platform_revenue,
                            row.commission_rate,
                            row.commission_amount,
                        )
                    )
                    or row.commission_rate > 1
                ):
                    raise ValueError("Unreconciled legacy money basis")
            payouts = list(
                (
                    await db.scalars(
                        select(PayoutRequestModel).where(
                            PayoutRequestModel.user_id == guard.user_id,
                            PayoutRequestModel.currency == guard.currency,
                            PayoutRequestModel.status.notin_(
                                [
                                    PayoutRequestStatus.CANCELLED,
                                    PayoutRequestStatus.DELETED,
                                ]
                            ),
                        )
                    )
                ).all()
            )
            if any(not self._money(row.amount) for row in payouts):
                raise ValueError("Unknown payout money basis")
            total_income = sum(
                (row.commission_amount for row in income), Decimal(0)
            )
            total_payout = sum(
                (row.amount for row in payouts if row.amount is not None),
                Decimal(0),
            )
            if total_income < total_payout:
                raise ValueError("Unreconciled negative legacy wallet")

    @staticmethod
    def _money(value: Any) -> bool:
        return (
            isinstance(value, (Decimal, int))
            and Decimal(value).is_finite()
            and value >= 0
        )

    async def _materialize_old_cases(
        self, actor_id: UUID, interaction_id: UUID | None, after: UUID | None
    ) -> None:
        from ugc_bot.domain.enums import InteractionStatus
        from ugc_bot.infrastructure.db.repositories.interactions import (
            _to_interaction_entity,
        )

        async with self.session_factory() as db:
            await self._authorize(db, actor_id)
            query = (
                select(InteractionModel.interaction_id)
                .where(
                    InteractionModel.status == InteractionStatus.ISSUE,
                    ~select(LegacyFinancialCaseModel.interaction_id)
                    .where(
                        LegacyFinancialCaseModel.interaction_id
                        == InteractionModel.interaction_id
                    )
                    .exists(),
                )
                .order_by(InteractionModel.interaction_id)
            )
            if interaction_id is not None:
                query = query.where(
                    InteractionModel.interaction_id == interaction_id
                )
            if after is not None:
                query = query.where(InteractionModel.interaction_id > after)
            ids = list((await db.scalars(query.limit(200))).all())
        # One source per transaction keeps the common lock order acyclic.
        for source_id in ids:
            async with self.session_factory.begin() as db:
                source = await db.scalar(
                    select(InteractionModel)
                    .where(InteractionModel.interaction_id == source_id)
                    .with_for_update()
                )
                await self._authorize(db, actor_id)
                if (
                    source is not None
                    and source.status == InteractionStatus.ISSUE
                ):
                    await GuardRepository(
                        self.session_factory
                    ).block_for_interaction(
                        _to_interaction_entity(source), session=db
                    )

    async def list_cases(
        self,
        actor_id: UUID,
        interaction_id: UUID | None = None,
        *,
        after: UUID | None = None,
        limit: int = 200,
        released: bool | None = None,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 200:
            raise ValueError("Case page limit must be between 1 and 200")
        await self._materialize_old_cases(actor_id, interaction_id, after)
        async with self.session_factory() as db:
            await self._authorize(db, actor_id)
            query = select(LegacyFinancialCaseModel).order_by(
                LegacyFinancialCaseModel.interaction_id,
            )
            if interaction_id is not None:
                query = query.where(
                    LegacyFinancialCaseModel.interaction_id == interaction_id
                )
            if after is not None:
                query = query.where(
                    LegacyFinancialCaseModel.interaction_id > after
                )
            if released is not None:
                query = query.where(
                    LegacyFinancialCaseModel.released == released
                )
            cases = (await db.scalars(query.limit(limit))).all()
            result = []
            for case in cases:
                events = (
                    await db.scalars(
                        select(LegacyFinancialCaseEventModel)
                        .where(
                            LegacyFinancialCaseEventModel.interaction_id
                            == case.interaction_id
                        )
                        .order_by(LegacyFinancialCaseEventModel.version)
                    )
                ).all()
                guards = (
                    await db.scalars(
                        select(LegacyFinancialGuardModel).where(
                            LegacyFinancialGuardModel.interaction_id
                            == case.interaction_id
                        )
                    )
                ).all()
                result.append(
                    {
                        "interaction_id": str(case.interaction_id),
                        "source": case.source,
                        "cause": case.cause,
                        "version": case.version,
                        "released": case.released,
                        "wallets": [
                            {"user_id": str(g.user_id), "currency": g.currency}
                            for g in guards
                        ],
                        "history": [
                            {
                                "actor_id": str(e.actor_id)
                                if e.actor_id
                                else None,
                                "decision": e.decision,
                                "reason": e.reason,
                                "version": e.version,
                                "details": e.details,
                                "created_at": e.created_at.isoformat(),
                            }
                            for e in events
                        ],
                    }
                )
            return result
