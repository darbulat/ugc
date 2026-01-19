"""OpenAI-based blogger relevance selector."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from uuid import UUID

from openai import OpenAI

from ugc_bot.application.ports import BloggerRelevanceSelector
from ugc_bot.domain.entities import BloggerProfile, Order


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class OpenAIBloggerRelevanceSelector(BloggerRelevanceSelector):
    """Select relevant bloggers using OpenAI LLM."""

    api_key: str
    model: str
    temperature: float = 0.0

    def select(
        self,
        order: Order,
        profiles: list[BloggerProfile],
        limit: int,
    ) -> list[UUID]:
        """Select relevant blogger user ids."""

        if not profiles or limit <= 0:
            return []

        client = OpenAI(api_key=self.api_key)
        payload = {
            "order": {
                "product_link": order.product_link,
                "offer_text": order.offer_text,
                "ugc_requirements": order.ugc_requirements,
                "barter_description": order.barter_description,
                "price": order.price,
                "bloggers_needed": order.bloggers_needed,
            },
            "candidates": [
                {
                    "user_id": str(profile.user_id),
                    "instagram_url": profile.instagram_url,
                    "topics": profile.topics,
                    "audience_gender": profile.audience_gender.value,
                    "audience_age_min": profile.audience_age_min,
                    "audience_age_max": profile.audience_age_max,
                    "audience_geo": profile.audience_geo,
                    "price": profile.price,
                }
                for profile in profiles
            ],
            "limit": limit,
        }

        system_prompt = (
            "You are a matching engine for UGC offers. "
            "Return JSON with a single key 'user_ids' listing the best matching "
            "candidate user_id values as strings. Return at most 'limit' items."
        )
        user_prompt = json.dumps(payload, ensure_ascii=True)

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.temperature,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "{}"
            data = json.loads(content)
            raw_ids = data.get("user_ids", [])
        except Exception:
            logger.exception("OpenAI relevance selection failed")
            raw_ids = []

        valid_ids = {str(profile.user_id) for profile in profiles}
        selected: list[UUID] = []
        for value in raw_ids:
            if value in valid_ids:
                try:
                    selected.append(UUID(value))
                except ValueError:
                    continue
        return selected
