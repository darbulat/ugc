"""Authorized creator ratings, preserving each evaluator's history."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from uuid import UUID, uuid4

from ugc_bot.application.errors import InvalidRatingScoreError
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.ports import (
    BloggerRatingRepository,
    TransactionManager,
)
from ugc_bot.application.rating_eligibility_ports import (
    RatingEligibility,
    RatingEligibilityRepository,
)
from ugc_bot.domain.entities import BloggerRating
from ugc_bot.domain.enums import RaterRole
from ugc_bot.infrastructure.db.session import with_optional_tx


@dataclass(slots=True)
class BloggerRatingService:
    """Authorize against current ownership and completed work before writes."""

    rating_repo: BloggerRatingRepository
    transaction_manager: TransactionManager | None = None
    eligibility_repo: RatingEligibilityRepository | None = None

    async def _scope(
        self,
        actor_id: UUID,
        order_id: UUID,
        principal: AuthenticatedMessengerPrincipal | None,
        session: object | None,
        *,
        owner_only: bool = False,
    ) -> RatingEligibility:
        if self.eligibility_repo is None:
            raise ValueError("rating_eligibility_unavailable")
        return await self.eligibility_repo.load(
            actor_id,
            order_id,
            principal=principal,
            owner_only=owner_only,
            session=session,
        )

    async def rate_blogger(
        self,
        blogger_id: UUID,
        order_id: UUID,
        rater_id: UUID,
        rater_role: RaterRole,
        score: int,
        comment: str | None = None,
        session: object | None = None,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> BloggerRating:
        """Insert or update only this actor's rating, under the order lock.

        rater_role remains a compatible ingress argument; the current role is
        always derived from server-loaded ownership and manager assignments.
        """
        if type(score) is not int or not 1 <= score <= 5:
            raise InvalidRatingScoreError("Score must be in range [1, 5].")
        if comment is not None:
            if not isinstance(comment, str) or len(comment) > 2000:
                raise ValueError("rating_comment_invalid")
            comment = comment.strip() or None

        async def _run(sess: object | None) -> BloggerRating:
            scope = await self._scope(rater_id, order_id, principal, sess)
            participant = next(
                (
                    item
                    for item in scope.participants
                    if item.blogger_id == blogger_id
                ),
                None,
            )
            if participant is None:
                raise ValueError("rating_participant_required")
            if not participant.completed:
                raise ValueError("rating_work_incomplete")
            existing = await self.rating_repo.get_by_blogger_order_and_rater(
                blogger_id,
                order_id,
                rater_id,
                session=sess,
            )
            now = datetime.now(timezone.utc)
            if existing is not None:
                rating = replace(
                    existing,
                    rater_role=scope.role,
                    score=score,
                    comment=comment,
                    updated_at=now,
                )
            else:
                rating = BloggerRating(
                    rating_id=uuid4(),
                    blogger_id=blogger_id,
                    order_id=order_id,
                    rater_id=rater_id,
                    rater_role=scope.role,
                    score=score,
                    comment=comment,
                    created_at=now,
                )
            await self.rating_repo.save(rating, session=sess)
            return rating

        if session is not None:
            return await _run(session)
        return await with_optional_tx(self.transaction_manager, _run)

    async def has_completed_work(
        self,
        actor_id: UUID,
        order_id: UUID,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> bool:
        """Check actual work completion for the current order owner."""

        async def _run(sess: object | None) -> bool:
            scope = await self._scope(
                actor_id, order_id, principal, sess, owner_only=True
            )
            return any(
                participant.completed for participant in scope.participants
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def list_for_order(
        self,
        actor_id: UUID,
        order_id: UUID,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> list[dict]:
        """List the owner's participants and authored rating history."""

        async def _run(sess: object | None) -> list[dict]:
            scope = await self._scope(
                actor_id, order_id, principal, sess, owner_only=True
            )
            result = []
            for participant in scope.participants:
                history = [
                    item
                    for item in await self.rating_repo.list_by_blogger(
                        participant.blogger_id, session=sess
                    )
                    if item.order_id == order_id
                ]
                own = next(
                    (item for item in history if item.rater_id == actor_id),
                    None,
                )
                effective = await self.rating_repo.get_by_blogger_and_order(
                    participant.blogger_id, order_id, session=sess
                )
                result.append(
                    dict(
                        blogger_id=str(participant.blogger_id),
                        display_name=participant.display_name,
                        rating_eligible=participant.completed,
                        score=own.score if own else None,
                        comment=own.comment if own else None,
                        effective_score=effective.score if effective else None,
                        ratings=[
                            dict(
                                rater_id=str(item.rater_id),
                                rater_role=item.rater_role.value,
                                score=item.score,
                                comment=item.comment,
                            )
                            for item in history
                        ],
                    )
                )
            return result

        return await with_optional_tx(self.transaction_manager, _run)

    async def get_blogger_avg_rating(
        self, blogger_id: UUID, session: object | None = None
    ) -> float | None:
        """Return the average of one effective rating per creator/order."""
        if session is not None:
            return await self.rating_repo.get_avg_rating(
                blogger_id, session=session
            )

        async def _run(sess: object | None) -> float | None:
            return await self.rating_repo.get_avg_rating(
                blogger_id, session=sess
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def get_blogger_ratings(
        self, blogger_id: UUID, session: object | None = None
    ) -> list[BloggerRating]:
        """Return all authored ratings, including historical manager ratings."""
        if session is not None:
            return await self.rating_repo.list_by_blogger(
                blogger_id, session=session
            )

        async def _run(sess: object | None) -> list[BloggerRating]:
            return await self.rating_repo.list_by_blogger(
                blogger_id, session=sess
            )

        return await with_optional_tx(self.transaction_manager, _run)
