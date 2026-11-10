"""Paid order edits preserve payment terms and allow brief corrections."""

from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ugc_bot.admin import app as admin
from ugc_bot.domain.enums import OrderStatus


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        dict(order_type="barter"),
        dict(price=9000),
        dict(bloggers_needed=100),
        dict(financial_version=None),
    ],
)
async def test_financial_order_admin_rejects_frozen_field_changes(
    monkeypatch, changes
):
    order = NS(
        order_id=uuid4(),
        financial_version="approved-v1",
        status=OrderStatus.NEW,
        order_type="ugc_only",
        price=Decimal("1000.00"),
        bloggers_needed=30,
        geography="Москва",
        min_followers=1000,
        filter_by_placement=False,
    )
    view = admin.OrderAdmin()
    parent = AsyncMock()
    monkeypatch.setattr(admin, "_get_obj_by_pk", AsyncMock(return_value=order))
    monkeypatch.setattr(admin.ModelView, "update_model", parent)
    request = NS(form=AsyncMock(return_value={}))
    with pytest.raises(ValueError, match="financial_order_intake_immutable"):
        await view.update_model(request, str(order.order_id), changes)
    parent.assert_not_awaited()


@pytest.mark.asyncio
async def test_financial_order_admin_moderation_preserves_sources(
    monkeypatch,
):
    order = NS(
        order_id=uuid4(),
        financial_version="approved-v1",
        status=OrderStatus.NEW,
        price=Decimal("1000.00"),
        geography="Москва",
        filter_by_placement=False,
    )
    view = admin.OrderAdmin()
    parent = AsyncMock(return_value=order)
    monkeypatch.setattr(admin, "_get_obj_by_pk", AsyncMock(return_value=order))
    monkeypatch.setattr(admin.ModelView, "update_model", parent)
    managers = AsyncMock()
    geography = AsyncMock()
    monkeypatch.setattr(admin, "_update_order_managers", managers)
    monkeypatch.setattr(
        admin,
        "_update_order_location_geometry_after_geography_change",
        geography,
    )
    request = NS(form=AsyncMock(return_value={}))
    await view.update_model(
        request,
        str(order.order_id),
        dict(
            status="pending_moderation",
            price="1000.00",
            geography="Москва",
            filter_by_placement=False,
        ),
    )
    assert parent.await_args.args[-1] == dict(
        status="pending_moderation",
        price="1000.00",
        geography="Москва",
        filter_by_placement=False,
    )
    geography.assert_not_awaited()
    managers.assert_awaited_once()
