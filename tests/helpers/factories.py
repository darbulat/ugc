"""Factories for creating test entities."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from ugc_bot.domain.entities import (
    AdvertiserProfile,
    BloggerProfile,
    ContactPricing,
    Interaction,
    Order,
    User,
)
from ugc_bot.domain.enums import (
    AudienceGender,
    InteractionStatus,
    MessengerType,
    OrderStatus,
    OrderType,
    UserStatus,
    WorkFormat,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryAdvertiserProfileRepository,
    InMemoryBloggerProfileRepository,
    InMemoryContactPricingRepository,
    InMemoryInteractionRepository,
    InMemoryOrderRepository,
    InMemoryUserRepository,
)


async def create_test_user(
    user_repo: InMemoryUserRepository,
    user_id: UUID | None = None,
    external_id: str = "1",
    messenger_type: MessengerType = MessengerType.TELEGRAM,
    username: str = "test_user",
    status: UserStatus = UserStatus.ACTIVE,
    issue_count: int = 0,
    **kwargs,
) -> User:
    """Create and save test user.

    Args:
        user_repo: User repository
        user_id: Optional user ID (generated if not provided)
        external_id: External user ID
        messenger_type: Messenger type
        username: Username
        status: User status
        issue_count: Issue count
        **kwargs: Additional user fields

    Returns:
        Created user
    """
    if user_id is None:
        user_id = uuid4()

    user = User(
        user_id=user_id,
        external_id=external_id,
        messenger_type=messenger_type,
        username=username,
        status=status,
        issue_count=issue_count,
        created_at=kwargs.get("created_at", datetime.now(timezone.utc)),
        telegram=kwargs.get("telegram"),
    )
    await user_repo.save(user)
    return user


async def create_test_advertiser(
    user_repo: InMemoryUserRepository,
    advertiser_repo: InMemoryAdvertiserProfileRepository,
    user_id: UUID | None = None,
    external_id: str = "888",
    status: UserStatus = UserStatus.ACTIVE,
    phone: str = "+79001234567",
    brand: str = "Test Brand",
) -> UUID:
    """Create and save advertiser user with profile.

    Args:
        user_repo: User repository
        advertiser_repo: Advertiser profile repository
        user_id: Optional user ID (generated if not provided)
        external_id: External user ID
        status: User status
        phone: Phone for contact
        brand: Brand / company name

    Returns:
        User ID
    """
    user = await create_test_user(
        user_repo=user_repo,
        user_id=user_id,
        external_id=external_id,
        username="adv",
        status=status,
    )
    await advertiser_repo.save(
        AdvertiserProfile(
            user_id=user.user_id,
            phone=phone,
            brand=brand,
            site_link=None,
        )
    )
    return user.user_id


async def create_test_blogger_profile(
    blogger_repo: InMemoryBloggerProfileRepository,
    user_id: UUID,
    instagram_url: str = "https://instagram.com/test",
    confirmed: bool = True,
    topics: dict | None = None,
    audience_gender: AudienceGender = AudienceGender.ALL,
    audience_age_min: int = 18,
    audience_age_max: int = 35,
    audience_geo: str = "Moscow",
    price: float = 1000.0,
    **kwargs,
) -> BloggerProfile:
    """Create and save blogger profile.

    Args:
        blogger_repo: Blogger profile repository
        user_id: User ID
        instagram_url: Instagram URL
        confirmed: Whether Instagram is confirmed
        topics: Topics dictionary
        audience_gender: Audience gender
        audience_age_min: Minimum audience age
        audience_age_max: Maximum audience age
        audience_geo: Audience geography
        price: Price
        **kwargs: Additional profile fields

    Returns:
        Created blogger profile
    """
    if topics is None:
        topics = {"selected": ["tech"]}

    profile = BloggerProfile(
        user_id=user_id,
        instagram_url=instagram_url,
        confirmed=confirmed,
        city=kwargs.get("city", "Moscow"),
        topics=topics,
        audience_gender=audience_gender,
        audience_age_min=audience_age_min,
        audience_age_max=audience_age_max,
        audience_geo=audience_geo,
        price=price,
        barter=kwargs.get("barter", False),
        work_format=kwargs.get("work_format", WorkFormat.UGC_ONLY),
        updated_at=kwargs.get("updated_at", datetime.now(timezone.utc)),
    )
    await blogger_repo.save(profile)
    return profile


async def create_test_advertiser_profile(
    advertiser_repo: InMemoryAdvertiserProfileRepository,
    user_id: UUID,
    phone: str = "+79001234567",
    brand: str = "Test Brand",
    site_link: str | None = None,
) -> AdvertiserProfile:
    """Create and save advertiser profile.

    Args:
        advertiser_repo: Advertiser profile repository
        user_id: User ID
        phone: Phone for contact
        brand: Brand / company name
        site_link: Optional site link

    Returns:
        Created advertiser profile
    """
    profile = AdvertiserProfile(
        user_id=user_id,
        phone=phone,
        brand=brand,
        site_link=site_link,
    )
    await advertiser_repo.save(profile)
    return profile


async def create_test_order(
    order_repo: InMemoryOrderRepository,
    advertiser_id: UUID,
    order_id: UUID | None = None,
    order_type: OrderType = OrderType.UGC_ONLY,
    product_link: str = "https://example.com",
    offer_text: str = "Offer",
    ugc_requirements: str | None = None,
    barter_description: str | None = None,
    price: float = 1000.0,
    bloggers_needed: int = 3,
    status: OrderStatus = OrderStatus.NEW,
    created_at: datetime | None = None,
    contacts_sent_at: datetime | None = None,
) -> Order:
    """Create and save test order.

    Args:
        order_repo: Order repository
        advertiser_id: Advertiser user ID
        order_id: Optional order ID (generated if not provided)
        order_type: Order type (UGC only or UGC + placement)
        product_link: Product link
        offer_text: Offer text
        ugc_requirements: UGC requirements
        barter_description: Barter description
        price: Price
        bloggers_needed: Number of bloggers needed
        status: Order status
        created_at: Creation timestamp
        contacts_sent_at: Contacts sent timestamp

    Returns:
        Created order
    """
    if order_id is None:
        order_id = uuid4()

    if created_at is None:
        created_at = datetime.now(timezone.utc)

    order = Order(
        order_id=order_id,
        advertiser_id=advertiser_id,
        order_type=order_type,
        product_link=product_link,
        offer_text=offer_text,
        ugc_requirements=ugc_requirements,
        barter_description=barter_description,
        price=price,
        bloggers_needed=bloggers_needed,
        status=status,
        created_at=created_at,
        contacts_sent_at=contacts_sent_at,
    )
    await order_repo.save(order)
    return order


async def create_test_contact_pricing(
    pricing_repo: InMemoryContactPricingRepository,
    bloggers_count: int,
    price: float,
    updated_at: datetime | None = None,
) -> ContactPricing:
    """Create and save contact pricing.

    Args:
        pricing_repo: Contact pricing repository
        bloggers_count: Number of bloggers
        price: Price
        updated_at: Update timestamp

    Returns:
        Created contact pricing
    """
    if updated_at is None:
        updated_at = datetime.now(timezone.utc)

    pricing = ContactPricing(
        bloggers_count=bloggers_count,
        price=price,
        updated_at=updated_at,
    )
    await pricing_repo.save(pricing)
    return pricing


async def create_test_interaction(
    interaction_repo: InMemoryInteractionRepository,
    order_id: UUID,
    blogger_id: UUID,
    advertiser_id: UUID,
    interaction_id: UUID | None = None,
    status: InteractionStatus = InteractionStatus.PENDING,
    from_advertiser: str | None = None,
    from_blogger: str | None = None,
    postpone_count: int = 0,
    next_check_at: datetime | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> Interaction:
    """Create and save test interaction.

    Args:
        interaction_repo: Interaction repository
        order_id: Order ID
        blogger_id: Blogger user ID
        advertiser_id: Advertiser user ID
        interaction_id: Optional interaction ID (generated if not provided)
        status: Interaction status
        from_advertiser: Advertiser feedback
        from_blogger: Blogger feedback
        postpone_count: Number of postpones
        next_check_at: Next check timestamp
        created_at: Creation timestamp
        updated_at: Update timestamp

    Returns:
        Created interaction
    """
    if interaction_id is None:
        interaction_id = uuid4()

    if created_at is None:
        created_at = datetime.now(timezone.utc)

    if updated_at is None:
        updated_at = datetime.now(timezone.utc)

    interaction = Interaction(
        interaction_id=interaction_id,
        order_id=order_id,
        blogger_id=blogger_id,
        advertiser_id=advertiser_id,
        status=status,
        from_advertiser=from_advertiser,
        from_blogger=from_blogger,
        postpone_count=postpone_count,
        next_check_at=next_check_at,
        created_at=created_at,
        updated_at=updated_at,
    )
    await interaction_repo.save(interaction)
    return interaction
