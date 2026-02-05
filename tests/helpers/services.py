"""Service builders and fixtures for tests."""

from datetime import datetime, timezone

from ugc_bot.application.services.contact_pricing_service import (
    ContactPricingService,
)
from ugc_bot.application.services.order_service import OrderService
from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.application.services.payment_service import PaymentService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.entities import ContactPricing
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryAdvertiserProfileRepository,
    InMemoryBloggerProfileRepository,
    InMemoryContactPricingRepository,
    InMemoryOrderRepository,
    InMemoryOutboxRepository,
    InMemoryPaymentRepository,
    InMemoryUserRepository,
)


def build_profile_service(
    user_repo: InMemoryUserRepository,
    blogger_repo: InMemoryBloggerProfileRepository | None = None,
    advertiser_repo: InMemoryAdvertiserProfileRepository | None = None,
) -> ProfileService:
    """Build profile service for tests.

    Args:
        user_repo: User repository
        blogger_repo: Optional blogger repository (created if None)
        advertiser_repo: Optional advertiser repository (created if None)

    Returns:
        Profile service instance
    """
    if blogger_repo is None:
        blogger_repo = InMemoryBloggerProfileRepository()
    if advertiser_repo is None:
        advertiser_repo = InMemoryAdvertiserProfileRepository()

    return ProfileService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        advertiser_repo=advertiser_repo,
    )


def build_order_service(
    user_repo: InMemoryUserRepository,
    advertiser_repo: InMemoryAdvertiserProfileRepository,
    order_repo: InMemoryOrderRepository,
    transaction_manager: object | None = None,
) -> OrderService:
    """Build order service for tests.

    Args:
        user_repo: User repository
        advertiser_repo: Advertiser profile repository
        order_repo: Order repository
        transaction_manager: Optional transaction manager

    Returns:
        Order service instance
    """
    return OrderService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
        transaction_manager=transaction_manager,
    )


def build_user_role_service(
    user_repo: InMemoryUserRepository,
    transaction_manager: object | None = None,
) -> UserRoleService:
    """Build user role service for tests.

    Args:
        user_repo: User repository
        transaction_manager: Optional transaction manager

    Returns:
        User role service instance
    """
    return UserRoleService(
        user_repo=user_repo,
        transaction_manager=transaction_manager,
    )


def build_payment_service(
    user_repo: InMemoryUserRepository,
    advertiser_repo: InMemoryAdvertiserProfileRepository,
    order_repo: InMemoryOrderRepository,
    payment_repo: InMemoryPaymentRepository,
    transaction_manager: object,
    outbox_repo: InMemoryOutboxRepository | None = None,
) -> PaymentService:
    """Build payment service for tests.

    Args:
        user_repo: User repository
        advertiser_repo: Advertiser profile repository
        order_repo: Order repository
        payment_repo: Payment repository
        transaction_manager: Transaction manager (required)
        outbox_repo: Optional outbox repository (created if None)

    Returns:
        Payment service instance
    """
    if outbox_repo is None:
        outbox_repo = InMemoryOutboxRepository()

    outbox_publisher = OutboxPublisher(
        outbox_repo=outbox_repo, order_repo=order_repo
    )

    return PaymentService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
        payment_repo=payment_repo,
        outbox_publisher=outbox_publisher,
        transaction_manager=transaction_manager,
    )


async def build_contact_pricing_service(
    prices: dict[int, float] | None = None,
    pricing_repo: InMemoryContactPricingRepository | None = None,
) -> ContactPricingService:
    """Build contact pricing service with test data.

    Args:
        prices: Dictionary mapping blogger counts to prices
        pricing_repo: Optional pricing repository (created if None)

    Returns:
        Contact pricing service instance
    """
    if pricing_repo is None:
        pricing_repo = InMemoryContactPricingRepository()

    if prices:
        for count, price in prices.items():
            await pricing_repo.save(
                ContactPricing(
                    bloggers_count=count,
                    price=price,
                    updated_at=datetime.now(timezone.utc),
                )
            )

    return ContactPricingService(pricing_repo=pricing_repo)


def build_service_fixtures(
    user_repo: InMemoryUserRepository,
    blogger_repo: InMemoryBloggerProfileRepository | None = None,
    advertiser_repo: InMemoryAdvertiserProfileRepository | None = None,
    order_repo: InMemoryOrderRepository | None = None,
    transaction_manager: object | None = None,
) -> dict:
    """Build common service fixtures.

    Args:
        user_repo: User repository
        blogger_repo: Optional blogger repository
        advertiser_repo: Optional advertiser repository
        order_repo: Optional order repository
        transaction_manager: Optional transaction manager

    Returns:
        Dictionary with service instances
    """
    if blogger_repo is None:
        blogger_repo = InMemoryBloggerProfileRepository()
    if advertiser_repo is None:
        advertiser_repo = InMemoryAdvertiserProfileRepository()
    if order_repo is None:
        order_repo = InMemoryOrderRepository()

    return {
        "user_role_service": build_user_role_service(
            user_repo, transaction_manager
        ),
        "profile_service": build_profile_service(
            user_repo, blogger_repo, advertiser_repo
        ),
        "order_service": build_order_service(
            user_repo, advertiser_repo, order_repo, transaction_manager
        ),
    }
