"""Rating authorization and effective aggregation through concrete adapters."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from ugc_bot.application.errors import InvalidRatingScoreError
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.rating_eligibility_ports import RatingParticipant
from ugc_bot.application.services.blogger_rating_service import (
    BloggerRatingService,
)
from ugc_bot.domain.entities import BloggerRating, User
from ugc_bot.domain.enums import MessengerType, RaterRole, UserStatus
from ugc_bot.infrastructure.memory_rating_eligibility import (
    InMemoryRatingEligibilityRepository,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerRatingRepository,
)


@pytest.fixture
def flow():
    owner, manager, outsider, creator, order = (uuid4() for _ in range(5))
    now = datetime.now(timezone.utc)
    users = {
        user_id: User(
            user_id=user_id,
            messenger_type=MessengerType.TELEGRAM,
            username=str(user_id),
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=now,
            telegram_id=str(index),
        )
        for index, user_id in enumerate((owner, manager, outsider), 1)
    }
    eligibility = InMemoryRatingEligibilityRepository(
        users=users,
        owners={order: owner},
        managers={(manager, order)},
        participants={order: (RatingParticipant(creator, "Creator", True),)},
    )
    repo = InMemoryBloggerRatingRepository()
    service = BloggerRatingService(repo, eligibility_repo=eligibility)
    return service, repo, eligibility, owner, manager, outsider, creator, order


async def rate(flow, actor=None, score=5, **kwargs):
    service, _, _, owner, _, _, creator, order = flow
    return await service.rate_blogger(
        creator, order, actor or owner, RaterRole.ADMIN, score, **kwargs
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("score", [1, 5])
async def test_owner_can_rate_and_update_own_score(flow, score):
    service, repo, _, owner, manager, _, creator, order = flow
    historical = await rate(flow, manager, 3)
    first = await rate(flow, score=score, comment=" Nice ")
    updated = await rate(flow, score=4, comment=" Updated ")
    assert first.rater_role == RaterRole.ADVERTISER  # Never trust caller role.
    assert updated.rating_id == first.rating_id
    assert updated.created_at == first.created_at
    assert updated.updated_at is not None and updated.comment == "Updated"
    assert len(repo.ratings) == 2
    assert (
        await repo.get_by_blogger_order_and_rater(creator, order, manager)
        == historical
    )
    assert await repo.get_by_blogger_and_order(creator, order) == updated
    assert await service.get_blogger_avg_rating(creator) == 4
    listed = await service.list_for_order(owner, order)
    assert listed[0]["rating_eligible"] is True
    assert listed[0]["score"] == 4
    assert {item["rater_role"] for item in listed[0]["ratings"]} == {
        "advertiser",
        "manager",
    }


@pytest.mark.asyncio
async def test_existing_owner_rating_uses_current_owner_role_on_update(flow):
    service, repo, _, owner, manager, _, creator, order = flow
    previous = await rate(flow, score=3)
    await repo.save(replace(previous, rater_role=RaterRole.ADMIN))
    updated = await rate(flow, score=5)
    await rate(flow, actor=manager, score=1)
    assert updated.rating_id == previous.rating_id
    assert updated.rater_role == RaterRole.ADVERTISER
    assert (await repo.get_by_blogger_and_order(creator, order)).score == 5
    assert await service.get_blogger_avg_rating(creator) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("score", [0, 6, -1, True, False, 2.5, "5", None])
async def test_invalid_score_rejected_without_persistence(flow, score):
    with pytest.raises(InvalidRatingScoreError):
        await rate(flow, score=score)
    assert not flow[1].ratings


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "violation",
    [
        "outsider",
        "missing_participant",
        "incomplete",
        "blocked",
        "stale_principal",
    ],
)
async def test_current_authorization_and_actual_completion_required(
    flow, violation
):
    service, repo, eligibility, owner, _, outsider, creator, order = flow
    actor = owner
    kwargs = {}
    if violation == "outsider":
        actor = outsider
    elif violation == "missing_participant":
        eligibility.participants[order] = (
            RatingParticipant(uuid4(), "Other", True),
        )
    elif violation == "incomplete":
        eligibility.participants[order] = (
            RatingParticipant(creator, "Creator", False),
        )
    elif violation == "blocked":
        eligibility.users[owner] = replace(
            eligibility.users[owner], status=UserStatus.BLOCKED
        )
    else:
        kwargs["principal"] = AuthenticatedMessengerPrincipal(
            owner, "telegram", "old"
        )
    with pytest.raises(ValueError):
        await rate(flow, actor, **kwargs)
    assert not repo.ratings
    if violation == "incomplete":
        assert (await service.list_for_order(owner, order))[0][
            "rating_eligible"
        ] is False


@pytest.mark.asyncio
async def test_missing_eligibility_fails_closed(flow):
    with pytest.raises(ValueError, match="rating_eligibility_unavailable"):
        await BloggerRatingService(flow[1]).rate_blogger(
            flow[6], flow[7], flow[3], RaterRole.ADVERTISER, 5
        )


@pytest.mark.asyncio
async def test_manager_admin_roles_preserved_and_listing_owner_only(
    flow,
):
    service, repo, eligibility, owner, manager, outsider, _, order = flow
    eligibility.users[outsider] = replace(
        eligibility.users[outsider], admin=True
    )
    assert (await rate(flow, manager)).rater_role == RaterRole.MANAGER
    assert (await rate(flow, outsider)).rater_role == RaterRole.ADMIN
    for actor in (manager, outsider):
        with pytest.raises(ValueError, match="rating_access_denied"):
            await service.list_for_order(actor, order)
    eligibility.managers.clear()
    with pytest.raises(ValueError, match="rating_access_denied"):
        await rate(flow, manager)
    assert len(repo.ratings) == 2


@pytest.mark.asyncio
async def test_completed_work_signal_requires_owner_and_actual_completion(flow):
    service, _, eligibility, owner, manager, outsider, creator, order = flow
    assert await service.has_completed_work(owner, order) is True
    eligibility.participants[order] = (
        RatingParticipant(creator, "Creator", False),
    )
    assert await service.has_completed_work(owner, order) is False
    eligibility.participants[order] = ()
    assert await service.has_completed_work(owner, order) is False
    for actor in (manager, outsider):
        with pytest.raises(ValueError, match="rating_access_denied"):
            await service.has_completed_work(actor, order)


@pytest.mark.asyncio
async def test_effective_aggregation_uses_one_score_and_latest_fallback(
    flow,
):
    _, repo, _, owner, manager, outsider, creator, order = flow
    now = datetime.now(timezone.utc)

    def row(order_id, actor, role, score, at):
        return BloggerRating(
            uuid4(), creator, order_id, actor, role, score, None, at
        )

    await repo.save(row(order, manager, RaterRole.MANAGER, 1, now))
    await repo.save(
        row(order, outsider, RaterRole.ADMIN, 3, now + timedelta(seconds=1))
    )
    assert (await repo.get_by_blogger_and_order(creator, order)).score == 3
    advertiser = row(
        order, owner, RaterRole.ADVERTISER, 5, now - timedelta(days=1)
    )
    await repo.save(advertiser)
    other_order = uuid4()
    await repo.save(row(other_order, manager, RaterRole.MANAGER, 1, now))
    assert await repo.get_by_blogger_and_order(creator, order) == advertiser
    assert await repo.get_avg_rating(creator) == 3
    assert await repo.get_avg_ratings_for_bloggers([creator, uuid4()]) == {
        creator: 3
    }
    assert len(await repo.list_by_blogger(creator)) == 4


@pytest.mark.asyncio
async def test_valid_principal_and_comment_validation(flow):
    principal = AuthenticatedMessengerPrincipal(flow[3], "telegram", "1")
    assert (await rate(flow, principal=principal)).score == 5
    for comment in (True, "x" * 2001):
        with pytest.raises(ValueError, match="rating_comment_invalid"):
            await rate(flow, comment=comment)
