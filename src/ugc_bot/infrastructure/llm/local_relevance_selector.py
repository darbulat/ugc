"""Local fallback relevance selector."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from ugc_bot.application.ports import BloggerRelevanceSelector
from ugc_bot.domain.entities import BloggerProfile, Order


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LocalBloggerRelevanceSelector(BloggerRelevanceSelector):
    """Select bloggers deterministically without external calls."""

    def select(
        self,
        order: Order,
        profiles: list[BloggerProfile],
        limit: int,
    ) -> list[UUID]:
        """Return the first matching profiles up to the limit."""

        if not profiles or limit <= 0:
            return []

        logger.info(
            "Local selector used for order %s with %s candidates",
            order.order_id,
            len(profiles),
        )
        return [profile.user_id for profile in profiles][:limit]
