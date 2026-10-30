"""Repository SQL and mapping contracts; only database execution is replaced."""

from dataclasses import asdict
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from ugc_bot.domain.enums import RaterRole, WorkFormat
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    BloggerRatingModel,
)
from ugc_bot.infrastructure.db.repositories.profiles import (
    SqlAlchemyAdvertiserProfileRepository,
    SqlAlchemyBloggerProfileRepository,
)
from ugc_bot.infrastructure.db.repositories.ratings import (
    SqlAlchemyBloggerRatingRepository,
)


def compile_query(session, index=0):
    query = session.execute.await_args_list[index].args[0]
    compiled = query.compile(dialect=postgresql.dialect())
    return str(compiled), compiled.params


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["attribute", "invalid", "large"])
async def test_confirmed_blogger_geometry_errors_and_large_result_warning(
    failure, caplog
):
    session = Mock(spec=AsyncSession)
    session.sync_session = Mock()
    session.sync_session.get_bind.side_effect = (
        AttributeError("no dialect")
        if failure == "attribute"
        else ValueError("invalid geometry")
        if failure == "invalid"
        else None
    )
    ids = [uuid4() for _ in range(5001 if failure == "large" else 1)]
    result = Mock()
    result.scalars.return_value = ids
    session.execute = AsyncMock(return_value=result)
    repo = SqlAlchemyBloggerProfileRepository(Mock())
    actual = await repo.list_confirmed_user_ids(
        session=session, location_geometry_wkt="POINT(1 2)"
    )
    if failure == "invalid":
        assert actual == []
        session.execute.assert_not_awaited()
        assert "Invalid order location_geometry WKT" in caplog.text
    else:
        assert actual == ids
        sql, params = compile_query(session)
        assert "blogger_profiles.confirmed IS true" in sql
        assert "ST_Intersects" not in sql
        assert params == {}
        if failure == "large":
            assert "Large confirmed user ID set: 5001 bloggers" in caplog.text


def blogger_model():
    return BloggerProfileModel(
        user_id=uuid4(),
        instagram_url="https://instagram.com/alice",
        instagram_username="alice",
        price=15,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        confirmed=True,
        wanted_to_change_terms_count=0,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["indexed", "legacy", "absent", "empty"])
async def test_instagram_username_lookup_normalizes_and_uses_legacy_fallback(
    source,
):
    model = blogger_model()
    first = Mock()
    first.scalar_one_or_none.return_value = (
        model if source == "indexed" else None
    )
    second = Mock()
    second.scalar_one_or_none.return_value = (
        model if source == "legacy" else None
    )
    session = NS(execute=AsyncMock(side_effect=[first, second]))
    factory = Mock()
    repo = SqlAlchemyBloggerProfileRepository(factory)
    result = await repo.get_by_instagram_username(
        "" if source == "empty" else "/ALICE/", session=session
    )
    if source in {"indexed", "legacy"}:
        assert result.user_id == model.user_id
        assert result.instagram_username == "alice"
        assert result.price == 15.0
        assert result.work_format == WorkFormat.UGC_ONLY
    else:
        assert result is None
    factory.assert_not_called()
    if source == "empty":
        session.execute.assert_not_awaited()
        return
    sql, params = compile_query(session)
    assert "lower(blogger_profiles.instagram_username) =" in sql
    assert list(params.values()) == ["alice"]
    if source in {"legacy", "absent"}:
        sql, params = compile_query(session, 1)
        assert "lower(blogger_profiles.instagram_url) LIKE" in sql
        assert list(params.values()) == ["%instagram.com/alice"]
    else:
        assert session.execute.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("advertiser", [False, True])
@pytest.mark.parametrize("empty", [False, True])
async def test_batch_profiles_short_circuit_empty_ids_and_map_by_user(
    advertiser, empty
):
    model = (
        AdvertiserProfileModel(user_id=uuid4(), brand="Brand", contact="phone")
        if advertiser
        else blogger_model()
    )
    result = Mock()
    result.scalars.return_value.all.return_value = [model]
    session = NS(execute=AsyncMock(return_value=result))
    factory = Mock()
    cls = (
        SqlAlchemyAdvertiserProfileRepository
        if advertiser
        else SqlAlchemyBloggerProfileRepository
    )
    repo = cls(factory)
    ids = [] if empty else [model.user_id, uuid4()]
    profiles = await repo.get_by_user_ids(ids, session=session)
    if empty:
        assert profiles == {}
        session.execute.assert_not_awaited()
    else:
        assert list(profiles) == [model.user_id]
        assert profiles[model.user_id].user_id == model.user_id
        if advertiser:
            assert profiles[model.user_id].brand == "Brand"
            assert profiles[model.user_id].phone == "phone"
        sql, params = compile_query(session)
        assert "user_id IN" in sql
        assert list(params.values()) == [ids]
    factory.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("found", [False, True])
async def test_rating_lookup_filters_blogger_and_order_and_maps_all_fields(
    found,
):
    now = datetime.now(timezone.utc)
    model = BloggerRatingModel(
        rating_id=uuid4(),
        blogger_id=uuid4(),
        order_id=uuid4(),
        rater_id=uuid4(),
        rater_role=RaterRole.MANAGER,
        score=5,
        comment="Excellent",
        created_at=now,
        updated_at=now,
    )
    result = Mock()
    result.scalar_one_or_none.return_value = model if found else None
    session = NS(execute=AsyncMock(return_value=result))
    repo = SqlAlchemyBloggerRatingRepository(Mock())
    rating = await repo.get_by_blogger_and_order(
        model.blogger_id, model.order_id, session=session
    )
    if found:
        assert asdict(rating) == {
            key: getattr(model, key)
            for key in (
                "rating_id",
                "blogger_id",
                "order_id",
                "rater_id",
                "rater_role",
                "score",
                "comment",
                "created_at",
                "updated_at",
            )
        }
    else:
        assert rating is None
    sql, params = compile_query(session)
    assert "blogger_ratings.blogger_id =" in sql
    assert "blogger_ratings.order_id =" in sql
    assert params["blogger_id_1"] == model.blogger_id
    assert params["order_id_1"] == model.order_id
    assert params["rater_role_1"] == RaterRole.ADVERTISER
    assert "ORDER BY CASE" in sql and "LIMIT" in sql


@pytest.mark.asyncio
async def test_rating_list_is_newest_first_and_only_for_requested_blogger():
    model = BloggerRatingModel(
        rating_id=uuid4(),
        blogger_id=uuid4(),
        order_id=uuid4(),
        rater_id=uuid4(),
        rater_role=RaterRole.ADMIN,
        score=3,
        created_at=datetime.now(timezone.utc),
    )
    result = Mock()
    result.scalars.return_value = [model]
    session = NS(execute=AsyncMock(return_value=result))
    ratings = await SqlAlchemyBloggerRatingRepository(Mock()).list_by_blogger(
        model.blogger_id, session=session
    )
    assert len(ratings) == 1
    assert (ratings[0].rating_id, ratings[0].score) == (model.rating_id, 3)
    sql, params = compile_query(session)
    assert "ORDER BY blogger_ratings.created_at DESC" in sql
    assert list(params.values()) == [model.blogger_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [False, True])
async def test_rating_batch_averages_group_by_blogger_and_skip_nulls(empty):
    first, second = uuid4(), uuid4()
    result = Mock()
    result.all.return_value = [(first, 4), (second, None)]
    session = NS(execute=AsyncMock(return_value=result))
    ids = [] if empty else [first, second]
    averages = await SqlAlchemyBloggerRatingRepository(
        Mock()
    ).get_avg_ratings_for_bloggers(ids, session=session)
    assert averages == ({} if empty else {first: 4.0})
    if empty:
        session.execute.assert_not_awaited()
    else:
        sql, params = compile_query(session)
        assert "avg(anon_1.score)" in sql
        assert "GROUP BY anon_1.blogger_id" in sql
        assert "PARTITION BY blogger_ratings.blogger_id, " in sql
        assert "blogger_ratings.order_id" in sql
        assert params["blogger_id_1"] == ids
        assert params["rater_role_1"] == RaterRole.ADVERTISER
        assert params["position_1"] == 1
