"""A private active order can rehearse both creator invitation paths."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from scripts.prepare_invite_preview_order import provision
from tests.postgres_financial.test_creator_social import seed_profile
from tests.postgres_financial.test_telegram_order_summary import (
    financial_pg_engine,
    intake_env,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.services.invite_handoff_notices import (
    deliver_invite_notice,
)
from ugc_bot.container.creator_invite_factory import build_creator_invites
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    ManagerOrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.creator_invites import (
    create_invite,
    free_positions,
    order_for_invite,
)
from ugc_bot.infrastructure.db.repositories.invite_handoff import (
    recent_invitation,
)
from ugc_bot.infrastructure.db.repositories.invite_preview import (
    PREVIEW_CONSENT,
)

__all__ = ["financial_pg_engine", "intake_env"]


@pytest.mark.asyncio
async def test_preview_uses_private_card_and_never_captures_or_sends(
    intake_env,
):
    env = intake_env
    order_id = uuid4()
    owner = env["user"]
    manager = env["admin"]
    service = build_creator_invites(env["container"].transaction_manager)
    with Session(env["pg"]) as db, db.begin():
        db.get(UserModel, owner.user_id).telegram = "preview_owner"
        provision(db, order_id, "preview_owner")
        assert order_for_invite(db, order_id).complimentary
        db.add(
            ManagerOrderModel(
                order_id=order_id,
                user_id=manager.user_id,
                created_at=service.clock.now(),
            )
        )
        one, two = db.scalars(
            free_positions(order_id).order_by("ordinal")
        ).all()
        at = service.clock.now()
        creator_id = seed_profile(db, stable_id=uuid4().hex)
        db.get(UserModel, creator_id).telegram = "preview_creator"
        db.get(UserModel, creator_id).telegram_id = "1234567890"
        profile = db.scalar(
            select(BloggerProfileModel).where(
                BloggerProfileModel.user_id == creator_id
            )
        )
        profile.instagram_url = "https://instagram.com/preview_creator"
        db.flush()
        manual = create_invite(
            db,
            order_id,
            one.paid_item_id,
            manager.user_id,
            "@staff_test",
            at,
            consent_source="instagram",
            telegram="@staff_test",
        )
        link = create_invite(
            db,
            order_id,
            None,
            manager.user_id,
            "@preview_creator",
            at,
            telegram="@preview_creator",
            direct=True,
        )
        assert (
            create_invite(
                db,
                order_id,
                None,
                manager.user_id,
                "@preview_creator",
                at,
                telegram="@preview_creator",
                direct=True,
            )
            == link
        )
        wrong = create_invite(
            db,
            order_id,
            two.paid_item_id,
            manager.user_id,
            "@wrong_profile",
            at,
        )
    client = AuthenticatedMessengerPrincipal(
        owner.user_id, "telegram", owner.telegram_id
    )
    outsider = AuthenticatedMessengerPrincipal(
        manager.user_id, "telegram", manager.telegram_id
    )
    rows = await service.preview_card(client, order_id)
    assert [row.telegram for row in rows] == ["staff_test", None]
    with pytest.raises(PermissionError):
        await service.preview_card(outsider, order_id)
    with pytest.raises(ValueError, match="principal_changed"):
        await service.preview_card(
            AuthenticatedMessengerPrincipal(owner.user_id, "telegram", "0"),
            order_id,
        )
    assert await service.claim_manager_notice(manual) is None

    with pytest.raises(ValueError, match="unavailable"):
        await service.accept(wrong, owner.user_id)
    with pytest.raises(ValueError, match="verified_creator"):
        await service.accept(wrong, manager.user_id)
    with pytest.raises(ValueError, match="instagram_mismatch"):
        await service.accept(wrong, creator_id)
    mock_bot = SimpleNamespace(send_message=AsyncMock())
    assert await service.creator_contact(link, creator_id) is None
    with pytest.raises(PermissionError):
        await service.client_sharing(outsider, order_id, True)
    await service.client_sharing(client, order_id, True)
    assert (
        await deliver_invite_notice(service, mock_bot, link, "creator")
        == "sent"
    )
    assert (
        await deliver_invite_notice(service, mock_bot, link, "creator") is None
    )
    assert (
        await deliver_invite_notice(service, mock_bot, link, "customer") is None
    )
    assert (
        await deliver_invite_notice(service, mock_bot, manual, "customer")
        is None
    )
    assert mock_bot.send_message.call_args.kwargs["chat_id"] == 1234567890
    await service.open_invite(link, creator_id)
    assert (
        await recent_invitation(
            service.transactions, creator_id, service.clock.now()
        )
        == link
    )
    await service.accept(link, creator_id)
    assert await service.creator_contact(link, creator_id) == (
        "Заказчик",
        "@preview_owner",
    )
    assert await service.creator_contact(link, manager.user_id) is None
    await service.client_sharing(client, order_id, False)
    assert await service.creator_contact(link, creator_id) is None
    assert (
        await deliver_invite_notice(service, mock_bot, link, "customer")
        == "sent"
    )
    assert (
        await deliver_invite_notice(service, mock_bot, link, "customer") is None
    )
    assert mock_bot.send_message.call_args.kwargs["chat_id"] == int(
        owner.telegram_id
    )
    assert mock_bot.send_message.await_count == 2
    assert await service.claim_manager_notice(link) == (
        int(manager.telegram_id),
        order_id,
        2,
    )
    await service.accept(link, creator_id)
    assert await service.claim_manager_notice(link) is None
    rows = await service.preview_card(client, order_id)
    assert rows[1].telegram == "preview_creator"
    assert rows[1].consent_source == PREVIEW_CONSENT
    assert await service.delivery.run_once() == 0
    with Session(env["pg"]) as db, db.begin():
        assert provision(db, order_id, "preview_owner") == order_id
        db.get(
            type(order_for_invite(db, order_id)), order_id
        ).dispatch_stopped = False
        db.flush()
        assert order_for_invite(db, order_id) is None
        assert db.scalars(free_positions(order_id)).all() == []
