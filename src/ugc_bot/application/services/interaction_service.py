"""Service for feedback interactions."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from ugc_bot.application.ports import InteractionRepository
from ugc_bot.domain.entities import Interaction
from ugc_bot.domain.enums import InteractionStatus


@dataclass(slots=True)
class InteractionService:
    """Handle interaction feedback and aggregation."""

    interaction_repo: InteractionRepository
    postpone_delay_hours: int = 72
    max_postpone_count: int = 3

    def create_for_contacts_sent(
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
        self.interaction_repo.save(interaction)
        return interaction

    def get_or_create(
        self, order_id: UUID, blogger_id: UUID, advertiser_id: UUID
    ) -> Interaction:
        """Fetch existing interaction or create a new one."""

        existing = self.interaction_repo.get_by_participants(
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
        self.interaction_repo.save(interaction)
        return interaction

    def record_advertiser_feedback(
        self, interaction_id: UUID, feedback_text: str
    ) -> Interaction:
        """Record advertiser feedback and update status."""

        interaction = self._require(interaction_id)
        outcome = self._parse_feedback(feedback_text)

        # Handle postpone case
        if outcome == InteractionStatus.PENDING:
            return self._postpone_interaction(interaction, "advertiser", feedback_text)

        # Check if we need to auto-resolve after max postpones
        if interaction.postpone_count >= self.max_postpone_count:
            outcome = InteractionStatus.NO_DEAL

        updated = Interaction(
            interaction_id=interaction.interaction_id,
            order_id=interaction.order_id,
            blogger_id=interaction.blogger_id,
            advertiser_id=interaction.advertiser_id,
            status=self._aggregate(feedback_text, interaction.from_blogger),
            from_advertiser=feedback_text,
            from_blogger=interaction.from_blogger,
            postpone_count=interaction.postpone_count,
            next_check_at=None
            if outcome != InteractionStatus.PENDING
            else interaction.next_check_at,
            created_at=interaction.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        self.interaction_repo.save(updated)
        return updated

    def record_blogger_feedback(
        self, interaction_id: UUID, feedback_text: str
    ) -> Interaction:
        """Record blogger feedback and update status."""

        interaction = self._require(interaction_id)
        outcome = self._parse_feedback(feedback_text)

        # Handle postpone case
        if outcome == InteractionStatus.PENDING:
            return self._postpone_interaction(interaction, "blogger", feedback_text)

        # Check if we need to auto-resolve after max postpones
        if interaction.postpone_count >= self.max_postpone_count:
            outcome = InteractionStatus.NO_DEAL

        updated = Interaction(
            interaction_id=interaction.interaction_id,
            order_id=interaction.order_id,
            blogger_id=interaction.blogger_id,
            advertiser_id=interaction.advertiser_id,
            status=self._aggregate(interaction.from_advertiser, feedback_text),
            from_advertiser=interaction.from_advertiser,
            from_blogger=feedback_text,
            postpone_count=interaction.postpone_count,
            next_check_at=None
            if outcome != InteractionStatus.PENDING
            else interaction.next_check_at,
            created_at=interaction.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        self.interaction_repo.save(updated)
        return updated

    def _postpone_interaction(
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
            postpone_count=interaction.postpone_count + 1,
            next_check_at=next_check,
            created_at=interaction.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        self.interaction_repo.save(updated)
        return updated

    def _require(self, interaction_id: UUID) -> Interaction:
        interaction = self.interaction_repo.get_by_id(interaction_id)
        if interaction is None:
            raise ValueError("Interaction not found.")
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
