"""Tests for OpenAI relevance selector."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from ugc_bot.domain.entities import BloggerProfile, Order
from ugc_bot.domain.enums import AudienceGender, OrderStatus
from ugc_bot.infrastructure.llm.openai_relevance_selector import (
    OpenAIBloggerRelevanceSelector,
)


def test_openai_relevance_selector_parses_ids(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Parse LLM response and filter unknown ids."""

    class FakeCompletions:
        def create(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            content = '{"user_ids": ["00000000-0000-0000-0000-000000000900", "bad"]}'
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )

    class FakeChat:
        def __init__(self) -> None:
            self.completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key
            self.chat = FakeChat()

    monkeypatch.setattr(
        "ugc_bot.infrastructure.llm.openai_relevance_selector.OpenAI",
        FakeOpenAI,
    )

    selector = OpenAIBloggerRelevanceSelector(
        api_key="test",
        model="gpt-4o-mini",
    )
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000901"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000902"),
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    profiles = [
        BloggerProfile(
            user_id=UUID("00000000-0000-0000-0000-000000000900"),
            instagram_url="https://instagram.com/blogger",
            confirmed=True,
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=datetime.now(timezone.utc),
        )
    ]

    selected = selector.select(order=order, profiles=profiles, limit=1)
    assert selected == [profiles[0].user_id]


def test_openai_relevance_selector_handles_errors(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Return empty list on OpenAI errors."""

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

        @property
        def chat(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "ugc_bot.infrastructure.llm.openai_relevance_selector.OpenAI",
        FakeOpenAI,
    )

    selector = OpenAIBloggerRelevanceSelector(
        api_key="test",
        model="gpt-4o-mini",
    )
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000910"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000911"),
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    profiles = [
        BloggerProfile(
            user_id=UUID("00000000-0000-0000-0000-000000000912"),
            instagram_url="https://instagram.com/blogger",
            confirmed=True,
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=datetime.now(timezone.utc),
        )
    ]

    assert selector.select(order=order, profiles=profiles, limit=1) == []


def test_openai_relevance_selector_handles_invalid_uuid(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Skip invalid UUID values from LLM."""

    class FakeCompletions:
        def create(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            content = '{"user_ids": ["00000000-0000-0000-0000-000000000920"]}'
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )

    class FakeChat:
        def __init__(self) -> None:
            self.completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key
            self.chat = FakeChat()

    def fake_uuid(value: str) -> UUID:  # type: ignore[no-untyped-def]
        raise ValueError("invalid")

    monkeypatch.setattr(
        "ugc_bot.infrastructure.llm.openai_relevance_selector.OpenAI",
        FakeOpenAI,
    )
    monkeypatch.setattr(
        "ugc_bot.infrastructure.llm.openai_relevance_selector.UUID",
        fake_uuid,
    )

    selector = OpenAIBloggerRelevanceSelector(
        api_key="test",
        model="gpt-4o-mini",
    )
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000921"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000922"),
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    profiles = [
        BloggerProfile(
            user_id=UUID("00000000-0000-0000-0000-000000000920"),
            instagram_url="https://instagram.com/blogger",
            confirmed=True,
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=datetime.now(timezone.utc),
        )
    ]

    assert selector.select(order=order, profiles=profiles, limit=1) == []


def test_openai_relevance_selector_limit_zero() -> None:
    """Return empty when limit <= 0."""

    selector = OpenAIBloggerRelevanceSelector(
        api_key="test",
        model="gpt-4o-mini",
    )
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000930"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000931"),
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    profiles = [
        BloggerProfile(
            user_id=UUID("00000000-0000-0000-0000-000000000932"),
            instagram_url="https://instagram.com/blogger",
            confirmed=True,
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=datetime.now(timezone.utc),
        )
    ]

    assert selector.select(order=order, profiles=profiles, limit=0) == []
