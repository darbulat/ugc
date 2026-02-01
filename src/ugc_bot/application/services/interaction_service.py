"""Service for feedback interactions."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from ugc_bot.application.errors import InteractionError, InteractionNotFoundError
from ugc_bot.application.ports import InteractionRepository, TransactionManager
from ugc_bot.domain.entities import Interaction
from ugc_bot.domain.enums import InteractionStatus

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InteractionService:
    """Handle interaction feedback and aggregation."""

    interaction_repo: InteractionRepository
    postpone_delay_hours: int = 72
    max_postpone_count: int = 3
    metrics_collector: Optional[Any] = None
    transaction_manager: TransactionManager | None = None

    async def _save(self, interaction: Interaction) -> None:
        """Persist interaction using an optional transaction boundary."""

        if self.transaction_manager is None:
            await self.interaction_repo.save(interaction)
            return
        async with self.transaction_manager.transaction() as session:
            await self.interaction_repo.save(interaction, session=session)

    async def get_interaction(self, interaction_id: UUID) -> Interaction | None:
        """Fetch interaction by id within a transaction boundary."""

        return await self._get_by_id(interaction_id)

    async def _get_by_id(self, interaction_id: UUID) -> Interaction | None:
        """Fetch interaction by id using an optional transaction boundary."""

        if self.transaction_manager is None:
            return await self.interaction_repo.get_by_id(interaction_id)
        async with self.transaction_manager.transaction() as session:
            return await self.interaction_repo.get_by_id(
                interaction_id, session=session
            )

    async def _get_by_participants(
        self, order_id: UUID, blogger_id: UUID, advertiser_id: UUID
    ) -> Interaction | None:
        """Fetch interaction by participants using an optional transaction boundary."""

        if self.transaction_manager is None:
            return await self.interaction_repo.get_by_participants(
                order_id=order_id, blogger_id=blogger_id, advertiser_id=advertiser_id
            )
        async with self.transaction_manager.transaction() as session:
            return await self.interaction_repo.get_by_participants(
                order_id=order_id,
                blogger_id=blogger_id,
                advertiser_id=advertiser_id,
                session=session,
            )

    async def create_for_contacts_sent(
        self, order_id: UUID, blogger_id: UUID, advertiser_id: UUID
    ) -> Interaction:
        """Create interaction when contacts are sent, with initial next_check_at."""

        now = datetime.now(timezone.utc)
        next_check = now + timedelta(hours=self.postpone_delay_hours)

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
        await self._save(interaction)
        return interaction

    async def schedule_next_reminder(
        self, interaction_id: UUID, next_check_at: datetime
    ) -> None:
        """Set next_check_at for an interaction (e.g. next 10:00 after sending feedback request)."""

        interaction = await self._get_by_id(interaction_id)
        if interaction is None:
            return
        updated = Interaction(
            interaction_id=interaction.interaction_id,
            order_id=interaction.order_id,
            blogger_id=interaction.blogger_id,
            advertiser_id=interaction.advertiser_id,
            status=interaction.status,
            from_advertiser=interaction.from_advertiser,
            from_blogger=interaction.from_blogger,
            postpone_count=interaction.postpone_count,
            next_check_at=next_check_at,
            created_at=interaction.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        await self._save(updated)

    async def get_or_create(
        self, order_id: UUID, blogger_id: UUID, advertiser_id: UUID
    ) -> Interaction:
        """Fetch existing interaction or create a new one."""

        existing = await self._get_by_participants(
            order_id=order_id, blogger_id=blogger_id, advertiser_id=advertiser_id
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
        await self._save(interaction)
        return interaction

    async def record_advertiser_feedback(
        self, interaction_id: UUID, feedback_text: str
    ) -> Interaction:
        """Record advertiser feedback and update status."""

        interaction = await self._require(interaction_id)
        outcome = self._parse_feedback(feedback_text)

        # Handle postpone case
        if outcome == InteractionStatus.PENDING:
            return await self._postpone_interaction(
                interaction, "advertiser", feedback_text
            )

        # Check if we need to auto-resolve after max postpones
        if interaction.postpone_count >= self.max_postpone_count:
            outcome = InteractionStatus.NO_DEAL

        final_status = self._aggregate(feedback_text, interaction.from_blogger)
        updated = Interaction(
            interaction_id=interaction.interaction_id,
            order_id=interaction.order_id,
            blogger_id=interaction.blogger_id,
            advertiser_id=interaction.advertiser_id,
            status=final_status,
            from_advertiser=feedback_text,
            from_blogger=interaction.from_blogger,
            postpone_count=interaction.postpone_count,
            next_check_at=None
            if outcome != InteractionStatus.PENDING
            else interaction.next_check_at,
            created_at=interaction.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        await self._save(updated)

        # Record ISSUE metric
        if final_status == InteractionStatus.ISSUE and self.metrics_collector:
            self.metrics_collector.record_interaction_issue(
                interaction_id=str(interaction.interaction_id),
                order_id=str(interaction.order_id),
                blogger_id=str(interaction.blogger_id),
                advertiser_id=str(interaction.advertiser_id),
            )

        return updated

    async def record_blogger_feedback(
        self, interaction_id: UUID, feedback_text: str
    ) -> Interaction:
        """Record blogger feedback and update status."""

        interaction = await self._require(interaction_id)
        outcome = self._parse_feedback(feedback_text)

        # Handle postpone case
        if outcome == InteractionStatus.PENDING:
            return await self._postpone_interaction(
                interaction, "blogger", feedback_text
            )

        # Check if we need to auto-resolve after max postpones
        if interaction.postpone_count >= self.max_postpone_count:
            outcome = InteractionStatus.NO_DEAL

        final_status = self._aggregate(interaction.from_advertiser, feedback_text)
        updated = Interaction(
            interaction_id=interaction.interaction_id,
            order_id=interaction.order_id,
            blogger_id=interaction.blogger_id,
            advertiser_id=interaction.advertiser_id,
            status=final_status,
            from_advertiser=interaction.from_advertiser,
            from_blogger=feedback_text,
            postpone_count=interaction.postpone_count,
            next_check_at=None
            if outcome != InteractionStatus.PENDING
            else interaction.next_check_at,
            created_at=interaction.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        await self._save(updated)

        # Record ISSUE metric
        if final_status == InteractionStatus.ISSUE and self.metrics_collector:
            self.metrics_collector.record_interaction_issue(
                interaction_id=str(interaction.interaction_id),
                order_id=str(interaction.order_id),
                blogger_id=str(interaction.blogger_id),
                advertiser_id=str(interaction.advertiser_id),
            )

        return updated

    async def _postpone_interaction(
        self, interaction: Interaction, side: str, feedback_text: str
    ) -> Interaction:
        """Postpone interaction check by 72 hours."""

        if interaction.postpone_count >= self.max_postpone_count:
            # Auto-resolve as NO_DEAL after max postpones
            next_check = None
            new_status = InteractionStatus.NO_DEAL
        else:
            next_check = datetime.now(timezone.utc) + timedelta(
                hours=self.postpone_delay_hours
            )
            new_status = InteractionStatus.PENDING

        new_postpone_count = interaction.postpone_count + 1
        updated = Interaction(
            interaction_id=interaction.interaction_id,
            order_id=interaction.order_id,
            blogger_id=interaction.blogger_id,
            advertiser_id=interaction.advertiser_id,
            status=new_status,
            from_advertiser=feedback_text
            if side == "advertiser"
            else interaction.from_advertiser,
            from_blogger=feedback_text
            if side == "blogger"
            else interaction.from_blogger,
            postpone_count=new_postpone_count,
            next_check_at=next_check,
            created_at=interaction.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        await self._save(updated)

        # Record postponement metric
        if self.metrics_collector:
            self.metrics_collector.record_feedback_postponement(
                interaction_id=str(interaction.interaction_id),
                postpone_count=new_postpone_count,
            )

        return updated

    async def _require(self, interaction_id: UUID) -> Interaction:
        interaction = await self._get_by_id(interaction_id)
        if interaction is None:
            raise InteractionNotFoundError("Interaction not found.")
        return interaction

    @staticmethod
    def _parse_feedback(feedback_text: str) -> InteractionStatus:
        """Parse feedback text to InteractionStatus."""

        feedback_lower = feedback_text.lower()
        if "еще не связался" in feedback_lower or "⏳" in feedback_text:
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
            InteractionService._parse_feedback(from_blogger) if from_blogger else None
        )

        # If either side has ISSUE, result is ISSUE (even if other side hasn't responded)
        if adv == InteractionStatus.ISSUE or blog == InteractionStatus.ISSUE:
            return InteractionStatus.ISSUE

        # If either side has OK, result is OK (even if other side hasn't responded)
        if adv == InteractionStatus.OK or blog == InteractionStatus.OK:
            return InteractionStatus.OK

        # If either side chose PENDING (explicit postpone), result is PENDING
        if adv == InteractionStatus.PENDING or blog == InteractionStatus.PENDING:
            return InteractionStatus.PENDING

        # If only one side responded with NO_DEAL, wait for other side (PENDING)
        if (adv is None and blog == InteractionStatus.NO_DEAL) or (
            blog is None and adv == InteractionStatus.NO_DEAL
        ):
            return InteractionStatus.PENDING

        # If both sides have NO_DEAL, result is NO_DEAL
        if adv == InteractionStatus.NO_DEAL and blog == InteractionStatus.NO_DEAL:
            return InteractionStatus.NO_DEAL

        # Default to PENDING if neither side responded
        if adv is None and blog is None:
            return InteractionStatus.PENDING

        return InteractionStatus.NO_DEAL

    async def manually_resolve_issue(
        self, interaction_id: UUID, final_status: InteractionStatus
    ) -> Interaction:
        """Manually resolve ISSUE interaction with final status."""

        if final_status not in (InteractionStatus.OK, InteractionStatus.NO_DEAL):
            raise InteractionError(
                "Final status must be OK or NO_DEAL for manual resolution."
            )

        interaction = await self._require(interaction_id)
        if interaction.status != InteractionStatus.ISSUE:
            raise InteractionError("Interaction is not in ISSUE status.")

        resolved = Interaction(
            interaction_id=interaction.interaction_id,
            order_id=interaction.order_id,
            blogger_id=interaction.blogger_id,
            advertiser_id=interaction.advertiser_id,
            status=final_status,
            from_advertiser=interaction.from_advertiser,
            from_blogger=interaction.from_blogger,
            postpone_count=interaction.postpone_count,
            next_check_at=None,
            created_at=interaction.created_at,
            updated_at=datetime.now(timezone.utc),
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
