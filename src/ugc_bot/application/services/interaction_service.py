"""Service for feedback interactions."""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from ugc_bot.application.ports import InteractionRepository
from ugc_bot.domain.entities import Interaction
from ugc_bot.domain.enums import InteractionStatus


@dataclass(slots=True)
class InteractionService:
    """Handle interaction feedback and aggregation."""

    interaction_repo: InteractionRepository

    def get_or_create(
        self, order_id: UUID, blogger_id: UUID, advertiser_id: UUID
    ) -> Interaction:
        """Fetch existing interaction or create a new one."""

        existing = self.interaction_repo.get_by_participants(
            order_id=order_id, blogger_id=blogger_id, advertiser_id=advertiser_id
        )
        if existing is not None:
            return existing

        interaction = Interaction(
            interaction_id=uuid4(),
            order_id=order_id,
            blogger_id=blogger_id,
            advertiser_id=advertiser_id,
            status=InteractionStatus.NO_DEAL,
            from_advertiser=None,
            from_blogger=None,
            created_at=datetime.now(timezone.utc),
        )
        self.interaction_repo.save(interaction)
        return interaction

    def record_advertiser_feedback(
        self, interaction_id: UUID, outcome: InteractionStatus
    ) -> Interaction:
        """Record advertiser feedback and update status."""

        interaction = self._require(interaction_id)
        updated = Interaction(
            interaction_id=interaction.interaction_id,
            order_id=interaction.order_id,
            blogger_id=interaction.blogger_id,
            advertiser_id=interaction.advertiser_id,
            status=self._aggregate(outcome, interaction.from_blogger),
            from_advertiser=outcome.value,
            from_blogger=interaction.from_blogger,
            created_at=interaction.created_at,
        )
        self.interaction_repo.save(updated)
        return updated

    def record_blogger_feedback(
        self, interaction_id: UUID, outcome: InteractionStatus
    ) -> Interaction:
        """Record blogger feedback and update status."""

        interaction = self._require(interaction_id)
        updated = Interaction(
            interaction_id=interaction.interaction_id,
            order_id=interaction.order_id,
            blogger_id=interaction.blogger_id,
            advertiser_id=interaction.advertiser_id,
            status=self._aggregate(interaction.from_advertiser, outcome),
            from_advertiser=interaction.from_advertiser,
            from_blogger=outcome.value,
            created_at=interaction.created_at,
        )
        self.interaction_repo.save(updated)
        return updated

    def _require(self, interaction_id: UUID) -> Interaction:
        interaction = self.interaction_repo.get_by_id(interaction_id)
        if interaction is None:
            raise ValueError("Interaction not found.")
        return interaction

    @staticmethod
    def _aggregate(
        from_advertiser: InteractionStatus | str | None,
        from_blogger: InteractionStatus | str | None,
    ) -> InteractionStatus:
        """Aggregate status based on both sides."""

        adv = InteractionStatus(from_advertiser) if from_advertiser else None
        blog = InteractionStatus(from_blogger) if from_blogger else None
        if InteractionStatus.ISSUE in {adv, blog}:
            return InteractionStatus.ISSUE
        if InteractionStatus.OK in {adv, blog}:
            return InteractionStatus.OK
        if adv == InteractionStatus.NO_DEAL and blog == InteractionStatus.NO_DEAL:
            return InteractionStatus.NO_DEAL
        return InteractionStatus.NO_DEAL
