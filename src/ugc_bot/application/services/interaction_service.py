"""Service for feedback interactions."""

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from ugc_bot.application.errors import (
    InteractionError,
    InteractionNotFoundError,
)
from ugc_bot.application.feedback_utils import (
    needs_feedback_reminder,
    next_reminder_datetime,
)
from ugc_bot.application.ports import (
    InteractionRepository,
    OrderRepository,
    TransactionManager,
    UserRepository,
)
from ugc_bot.domain.entities import Interaction
from ugc_bot.domain.enums import InteractionStatus, OrderStatus
from ugc_bot.infrastructure.db.session import with_optional_tx

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InteractionService:
    """Handle interaction feedback and aggregation."""

    interaction_repo: InteractionRepository
    postpone_delay_minutes: int = 4320
    max_postpone_count: int = 3
    metrics_collector: Optional[Any] = None
    transaction_manager: TransactionManager | None = None
    feedback_reminder_timezone: Optional[str] = None
    feedback_reminder_hour: int = 10
    feedback_reminder_minute: int = 0
    order_repo: OrderRepository | None = None
    user_repo: UserRepository | None = None
    referral_income_service: Optional[Any] = None

    async def _save(
        self, interaction: Interaction, *, session: object | None = None
    ) -> None:
        """Persist interaction using an optional transaction boundary."""

        async def _run(session: object | None):
            await self.interaction_repo.save(interaction, session=session)

        if session is not None:
            await _run(session)
        else:
            await with_optional_tx(self.transaction_manager, _run)

    async def get_interaction(self, interaction_id: UUID) -> Interaction | None:
        """Fetch interaction by id within a transaction boundary."""

        return await self._get_by_id(interaction_id)

    async def _get_by_id(self, interaction_id: UUID) -> Interaction | None:
        """Fetch interaction by id using an optional transaction boundary."""

        async def _run(session: object | None):
            return await self.interaction_repo.get_by_id(
                interaction_id, session=session
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def _get_by_participants(
        self,
        order_id: UUID,
        blogger_id: UUID,
        advertiser_id: UUID,
        *,
        session: object | None = None,
    ) -> Interaction | None:
        """Fetch interaction by participants (optional transaction boundary)."""

        async def _run(session: object | None):
            return await self.interaction_repo.get_by_participants(
                order_id=order_id,
                blogger_id=blogger_id,
                advertiser_id=advertiser_id,
                session=session,
            )

        if session is not None:
            return await _run(session)
        return await with_optional_tx(self.transaction_manager, _run)

    async def list_interactions_by_order(
        self, order_id: UUID
    ) -> list[Interaction]:
        """List interactions for order within a transaction boundary."""

        async def _run(session: object | None):
            return list(
                await self.interaction_repo.list_by_order(
                    order_id, session=session
                )
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def create_for_contacts_sent(
        self,
        order_id: UUID,
        blogger_id: UUID,
        advertiser_id: UUID,
        *,
        session: object | None = None,
    ) -> Interaction:
        """Create interaction when contacts sent, with initial next_check_at."""

        now = datetime.now(timezone.utc)
        next_check = now + timedelta(minutes=self.postpone_delay_minutes)

        interaction = Interaction(
            interaction_id=uuid4(),
            order_id=order_id,
            blogger_id=blogger_id,
            advertiser_id=advertiser_id,
            status=InteractionStatus.PENDING,
            from_advertiser=None,
            from_blogger=None,
            postpone_count=0,
            next_check_at=next_check,
            created_at=now,
            updated_at=now,
        )
        await self._save(interaction, session=session)
        return interaction

    async def reactivate_or_create_for_contacts_sent(
        self,
        order_id: UUID,
        blogger_id: UUID,
        advertiser_id: UUID,
        *,
        session: object | None = None,
    ) -> Interaction:
        """Reactivate contacts, retaining unresolved disputes and replies."""

        async def _run(session: object | None) -> Interaction:
            existing = await self.interaction_repo.get_by_participants(
                order_id, blogger_id, advertiser_id, session=session
            )
            if existing is not None:
                current = await self.interaction_repo.get_by_id_for_update(
                    existing.interaction_id, session=session
                )
                if current is None:
                    raise InteractionNotFoundError("Interaction not found.")
                if current.status == InteractionStatus.ISSUE:
                    return current
                now = datetime.now(timezone.utc)
                updated = replace(
                    current,
                    status=InteractionStatus.PENDING,
                    from_advertiser=None,
                    from_blogger=None,
                    postpone_count=0,
                    next_check_at=now
                    + timedelta(minutes=self.postpone_delay_minutes),
                    updated_at=now,
                )
            else:
                now = datetime.now(timezone.utc)
                updated = Interaction(
                    interaction_id=uuid4(),
                    order_id=order_id,
                    blogger_id=blogger_id,
                    advertiser_id=advertiser_id,
                    status=InteractionStatus.PENDING,
                    from_advertiser=None,
                    from_blogger=None,
                    postpone_count=0,
                    next_check_at=now
                    + timedelta(minutes=self.postpone_delay_minutes),
                    created_at=now,
                    updated_at=now,
                )
            await self.interaction_repo.save(updated, session=session)
            return updated

        if session is not None:
            return await _run(session)
        return await with_optional_tx(self.transaction_manager, _run)

    async def schedule_next_reminder(
        self, interaction_id: UUID, next_check_at: datetime
    ) -> None:
        """Schedule pending work without overwriting concurrent feedback."""

        async def _run(session: object | None) -> None:
            interaction = await self.interaction_repo.get_by_id_for_update(
                interaction_id, session=session
            )
            if (
                interaction is None
                or interaction.status != InteractionStatus.PENDING
            ):
                return
            updated = replace(
                interaction,
                next_check_at=next_check_at,
                updated_at=datetime.now(timezone.utc),
            )
            await self.interaction_repo.save(updated, session=session)

        await with_optional_tx(self.transaction_manager, _run)

    async def get_or_create(
        self,
        order_id: UUID,
        blogger_id: UUID,
        advertiser_id: UUID,
        *,
        session: object | None = None,
    ) -> Interaction:
        """Fetch existing interaction or create a new one."""

        existing = await self._get_by_participants(
            order_id=order_id,
            blogger_id=blogger_id,
            advertiser_id=advertiser_id,
            session=session,
        )
        if existing is not None:
            return existing

        now = datetime.now(timezone.utc)
        interaction = Interaction(
            interaction_id=uuid4(),
            order_id=order_id,
            blogger_id=blogger_id,
            advertiser_id=advertiser_id,
            status=InteractionStatus.PENDING,
            from_advertiser=None,
            from_blogger=None,
            postpone_count=0,
            next_check_at=None,
            created_at=now,
            updated_at=now,
        )
        await self._save(interaction, session=session)
        return interaction

    async def record_advertiser_feedback(
        self,
        interaction_id: UUID,
        feedback_text: str,
        *,
        session: object | None = None,
    ) -> Interaction:
        """Record advertiser feedback under the interaction row lock."""
        return await self._record_feedback(
            interaction_id, feedback_text, "advertiser", session=session
        )

    async def record_blogger_feedback(
        self, interaction_id: UUID, feedback_text: str
    ) -> Interaction:
        """Record blogger feedback under the same interaction row lock."""
        return await self._record_feedback(
            interaction_id, feedback_text, "blogger"
        )

    async def _record_feedback(
        self,
        interaction_id: UUID,
        feedback_text: str,
        side: str,
        *,
        session: object | None = None,
    ) -> Interaction:
        async def _op(session: object | None) -> Interaction:
            interaction = await self.interaction_repo.get_by_id_for_update(
                interaction_id, session=session
            )
            if interaction is None:
                raise InteractionError("Interaction not found")
            outcome = self._parse_feedback(feedback_text)
            if outcome == InteractionStatus.PENDING:
                if interaction.status == InteractionStatus.ISSUE:
                    return interaction
                return await self._postpone_interaction(
                    interaction, side, feedback_text, session=session
                )
            adv = (
                feedback_text
                if side == "advertiser"
                else interaction.from_advertiser
            )
            blog = (
                feedback_text if side == "blogger" else interaction.from_blogger
            )
            final_status = self._aggregate(adv, blog)
            if interaction.status == InteractionStatus.ISSUE:
                final_status = InteractionStatus.ISSUE
            other_missing = needs_feedback_reminder(
                blog if side == "advertiser" else adv
            )
            now = datetime.now(timezone.utc)
            if other_missing and final_status != InteractionStatus.ISSUE:
                effective_status = InteractionStatus.PENDING
                next_check = (
                    next_reminder_datetime(
                        self.feedback_reminder_timezone,
                        self.feedback_reminder_hour,
                        self.feedback_reminder_minute,
                    )
                    if self.feedback_reminder_timezone is not None
                    else now + timedelta(hours=24)
                )
            else:
                effective_status = final_status
                next_check = None
            updated = replace(
                interaction,
                from_advertiser=adv,
                from_blogger=blog,
                status=effective_status,
                next_check_at=next_check,
                updated_at=now,
            )
            await self.interaction_repo.save(updated, session=session)
            return updated

        if session is not None:
            return await _op(session)
        updated = await with_optional_tx(self.transaction_manager, _op)
        await self.after_feedback_commit(updated)
        return updated

    async def after_feedback_commit(self, updated: Interaction) -> None:
        """Run metrics/referral effects only after the caller committed."""
        if updated.status == InteractionStatus.ISSUE and self.metrics_collector:
            self.metrics_collector.record_interaction_issue(
                interaction_id=str(updated.interaction_id),
                order_id=str(updated.order_id),
                blogger_id=str(updated.blogger_id),
                advertiser_id=str(updated.advertiser_id),
            )
        if (
            updated.status == InteractionStatus.OK
            and self.referral_income_service
        ):
            await self._try_record_creator_referral_income(updated)

    async def _postpone_interaction(
        self,
        interaction: Interaction,
        side: str,
        feedback_text: str,
        session: object | None = None,
    ) -> Interaction:
        """Postpone check by configured delay (postpone_delay_minutes).

        When the other side has not responded yet, use next 24h reminder time
        so they continue receiving reminders. Only use 72h delay when both
        sides have responded with postpone.
        """

        if interaction.postpone_count >= self.max_postpone_count:
            # Auto-resolve as NO_DEAL after max postpones
            next_check = None
            new_status = InteractionStatus.NO_DEAL
        else:
            other_side_responded = (
                interaction.from_advertiser is not None
                if side == "blogger"
                else interaction.from_blogger is not None
            )
            if (
                not other_side_responded
                and self.feedback_reminder_timezone is not None
            ):
                next_check = next_reminder_datetime(
                    self.feedback_reminder_timezone,
                    self.feedback_reminder_hour,
                    self.feedback_reminder_minute,
                )
            else:
                next_check = datetime.now(timezone.utc) + timedelta(
                    minutes=self.postpone_delay_minutes
                )
            new_status = InteractionStatus.PENDING

        new_postpone_count = interaction.postpone_count + 1
        now = datetime.now(timezone.utc)
        updated = replace(
            interaction,
            status=new_status,
            from_advertiser=feedback_text
            if side == "advertiser"
            else interaction.from_advertiser,
            from_blogger=feedback_text
            if side == "blogger"
            else interaction.from_blogger,
            postpone_count=new_postpone_count,
            next_check_at=next_check,
            updated_at=now,
        )
        await self.interaction_repo.save(updated, session=session)

        # Record postponement metric
        if self.metrics_collector:
            self.metrics_collector.record_feedback_postponement(
                interaction_id=str(interaction.interaction_id),
                postpone_count=new_postpone_count,
            )

        return updated

    async def _try_record_creator_referral_income(
        self, interaction: Interaction
    ) -> None:
        """Record creator referral income if order is CLOSED."""
        if self.order_repo is None or self.user_repo is None:
            return
        try:
            order = await self.order_repo.get_by_id(interaction.order_id)
            if order and order.status == OrderStatus.CLOSED:
                advertiser = await self.user_repo.get_by_id(order.advertiser_id)
                if advertiser and advertiser.country:
                    svc: Any = self.referral_income_service
                    await svc.record_creator_referral_income(
                        order=order,
                        creator_id=interaction.blogger_id,
                        advertiser_country_code=advertiser.country,
                    )
        except Exception:
            logger.error(
                "Failed to record creator referral income for interaction %s",
                interaction.interaction_id,
                exc_info=True,
            )

    async def _require(self, interaction_id: UUID) -> Interaction:
        interaction = await self._get_by_id(interaction_id)
        if interaction is None:
            raise InteractionNotFoundError("Interaction not found.")
        return interaction

    @staticmethod
    def _parse_feedback(feedback_text: str) -> InteractionStatus:
        """Parse feedback text to InteractionStatus."""

        canonical = feedback_text.lstrip()
        for prefix, outcome in (
            ("⚠", InteractionStatus.ISSUE),
            ("⏳", InteractionStatus.PENDING),
            ("✅", InteractionStatus.OK),
            ("❌", InteractionStatus.NO_DEAL),
        ):
            if canonical.startswith(prefix):
                return outcome
        feedback_lower = feedback_text.lower()
        if (
            "еще не связался" in feedback_lower
            or "ещё не связался" in feedback_lower
            or "⏳" in feedback_text
        ):
            return InteractionStatus.PENDING
        if (
            "проблема" in feedback_lower
            or "мошенничество" in feedback_lower
            or "⚠️" in feedback_text
        ):
            return InteractionStatus.ISSUE
        if (
            "всё прошло" in feedback_lower
            or "сделка состоялась" in feedback_lower
            or "✅" in feedback_text
        ):
            return InteractionStatus.OK
        if "не договорились" in feedback_lower or "❌" in feedback_text:
            return InteractionStatus.NO_DEAL
        return InteractionStatus.NO_DEAL

    @staticmethod
    def _aggregate(
        from_advertiser: str | None,
        from_blogger: str | None,
    ) -> InteractionStatus:
        """Aggregate status based on both sides."""

        adv = (
            InteractionService._parse_feedback(from_advertiser)
            if from_advertiser
            else None
        )
        blog = (
            InteractionService._parse_feedback(from_blogger)
            if from_blogger
            else None
        )

        # ISSUE from either side => ISSUE (even if other hasn't responded)
        if adv == InteractionStatus.ISSUE or blog == InteractionStatus.ISSUE:
            return InteractionStatus.ISSUE

        # A success report contradicted by the other party is a dispute.
        if {adv, blog} == {InteractionStatus.OK, InteractionStatus.NO_DEAL}:
            return InteractionStatus.ISSUE

        # OK from either side => OK (even if other hasn't responded)
        if adv == InteractionStatus.OK or blog == InteractionStatus.OK:
            return InteractionStatus.OK

        # If either side chose PENDING (explicit postpone), result is PENDING
        if (
            adv == InteractionStatus.PENDING
            or blog == InteractionStatus.PENDING
        ):
            return InteractionStatus.PENDING

        # If only one side responded with NO_DEAL, wait for other side (PENDING)
        if (adv is None and blog == InteractionStatus.NO_DEAL) or (
            blog is None and adv == InteractionStatus.NO_DEAL
        ):
            return InteractionStatus.PENDING

        # If both sides have NO_DEAL, result is NO_DEAL
        if (
            adv == InteractionStatus.NO_DEAL
            and blog == InteractionStatus.NO_DEAL
        ):
            return InteractionStatus.NO_DEAL

        # Default to PENDING if neither side responded
        if adv is None and blog is None:
            return InteractionStatus.PENDING

        return InteractionStatus.NO_DEAL  # pragma: no cover

    async def manually_resolve_issue(
        self, interaction_id: UUID, final_status: InteractionStatus
    ) -> Interaction:
        """Manually resolve ISSUE interaction with final status."""

        if final_status not in (
            InteractionStatus.OK,
            InteractionStatus.NO_DEAL,
        ):
            raise InteractionError(
                "Final status must be OK or NO_DEAL for manual resolution."
            )

        interaction = await self._require(interaction_id)
        if interaction.status != InteractionStatus.ISSUE:
            raise InteractionError("Interaction is not in ISSUE status.")

        now = datetime.now(timezone.utc)
        resolved = replace(
            interaction,
            status=final_status,
            next_check_at=None,
            updated_at=now,
        )
        await self._save(resolved)

        logger.info(
            "Interaction issue manually resolved",
            extra={
                "interaction_id": str(interaction.interaction_id),
                "order_id": str(interaction.order_id),
                "blogger_id": str(interaction.blogger_id),
                "advertiser_id": str(interaction.advertiser_id),
                "final_status": final_status.value,
                "event_type": "interaction.issue_resolved",
            },
        )

        return resolved

    async def cancel_interaction(
        self,
        order_id: UUID,
        blogger_id: UUID,
        advertiser_id: UUID,
        *,
        session: object | None = None,
    ) -> None:
        """Cancel pending work without erasing disputes or final results."""

        async def _run(session: object | None) -> bool:
            existing = await self.interaction_repo.get_by_participants(
                order_id, blogger_id, advertiser_id, session=session
            )
            if existing is None:
                return False
            current = await self.interaction_repo.get_by_id_for_update(
                existing.interaction_id, session=session
            )
            if current is None or current.status in (
                InteractionStatus.OK,
                InteractionStatus.NO_DEAL,
                InteractionStatus.DELETED,
                InteractionStatus.ISSUE,
            ):
                return False
            await self.interaction_repo.save(
                replace(
                    current,
                    status=InteractionStatus.DELETED,
                    next_check_at=None,
                    updated_at=datetime.now(timezone.utc),
                ),
                session=session,
            )
            return True

        cancelled = (
            await _run(session)
            if session is not None
            else await with_optional_tx(self.transaction_manager, _run)
        )
        if cancelled and session is None:
            logger.info(
                "Interaction cancelled (creator removed from order)",
                extra={
                    "order_id": str(order_id),
                    "blogger_id": str(blogger_id),
                },
            )
