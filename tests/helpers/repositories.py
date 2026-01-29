"""Repository fixtures and utilities for tests."""

from typing import NamedTuple

import pytest

from ugc_bot.infrastructure.memory_repositories import (
    InMemoryAdvertiserProfileRepository,
    InMemoryBloggerProfileRepository,
    InMemoryComplaintRepository,
    InMemoryContactPricingRepository,
    InMemoryInteractionRepository,
    InMemoryInstagramVerificationRepository,
    InMemoryOrderRepository,
    InMemoryOrderResponseRepository,
    InMemoryOutboxRepository,
    InMemoryPaymentRepository,
    InMemoryUserRepository,
)


class InMemoryRepositories(NamedTuple):
    """Container for in-memory repositories."""

    user_repo: InMemoryUserRepository
    blogger_repo: InMemoryBloggerProfileRepository
    advertiser_repo: InMemoryAdvertiserProfileRepository
    order_repo: InMemoryOrderRepository
    order_response_repo: InMemoryOrderResponseRepository
    interaction_repo: InMemoryInteractionRepository
    payment_repo: InMemoryPaymentRepository
    pricing_repo: InMemoryContactPricingRepository
    outbox_repo: InMemoryOutboxRepository


def create_in_memory_repositories() -> InMemoryRepositories:
    """Create all in-memory repositories.

    Returns:
        Container with all repositories
    """
    return InMemoryRepositories(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        advertiser_repo=InMemoryAdvertiserProfileRepository(),
        order_repo=InMemoryOrderRepository(),
        order_response_repo=InMemoryOrderResponseRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        payment_repo=InMemoryPaymentRepository(),
        pricing_repo=InMemoryContactPricingRepository(),
        outbox_repo=InMemoryOutboxRepository(),
    )


@pytest.fixture
def user_repo() -> InMemoryUserRepository:
    """Fixture for user repository."""
    return InMemoryUserRepository()


@pytest.fixture
def blogger_repo() -> InMemoryBloggerProfileRepository:
    """Fixture for blogger profile repository."""
    return InMemoryBloggerProfileRepository()


@pytest.fixture
def advertiser_repo() -> InMemoryAdvertiserProfileRepository:
    """Fixture for advertiser profile repository."""
    return InMemoryAdvertiserProfileRepository()


@pytest.fixture
def order_repo() -> InMemoryOrderRepository:
    """Fixture for order repository."""
    return InMemoryOrderRepository()


@pytest.fixture
def order_response_repo() -> InMemoryOrderResponseRepository:
    """Fixture for order response repository."""
    return InMemoryOrderResponseRepository()


@pytest.fixture
def interaction_repo() -> InMemoryInteractionRepository:
    """Fixture for interaction repository."""
    return InMemoryInteractionRepository()


@pytest.fixture
def payment_repo() -> InMemoryPaymentRepository:
    """Fixture for payment repository."""
    return InMemoryPaymentRepository()


@pytest.fixture
def pricing_repo() -> InMemoryContactPricingRepository:
    """Fixture for contact pricing repository."""
    return InMemoryContactPricingRepository()


@pytest.fixture
def outbox_repo() -> InMemoryOutboxRepository:
    """Fixture for outbox repository."""
    return InMemoryOutboxRepository()


@pytest.fixture
def instagram_verification_repo() -> InMemoryInstagramVerificationRepository:
    """Fixture for Instagram verification repository."""
    return InMemoryInstagramVerificationRepository()


@pytest.fixture
def complaint_repo() -> InMemoryComplaintRepository:
    """Fixture for complaint repository."""
    return InMemoryComplaintRepository()


@pytest.fixture
def repos() -> InMemoryRepositories:
    """Fixture providing all repositories."""
    return create_in_memory_repositories()


def create_repository_fixtures() -> dict:
    """Create dictionary with all repositories.

    Returns:
        Dictionary with repository names as keys
    """
    repos = create_in_memory_repositories()
    return {
        "user_repo": repos.user_repo,
        "blogger_repo": repos.blogger_repo,
        "advertiser_repo": repos.advertiser_repo,
        "order_repo": repos.order_repo,
        "order_response_repo": repos.order_response_repo,
        "interaction_repo": repos.interaction_repo,
        "payment_repo": repos.payment_repo,
        "pricing_repo": repos.pricing_repo,
        "outbox_repo": repos.outbox_repo,
    }
