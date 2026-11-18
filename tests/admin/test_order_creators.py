"""One identity across offers, paid work and historical contact handoffs."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ugc_bot.admin.order_creators import creator_workspace


def test_workspace_keeps_historical_contact_price_and_work_in_one_row():
    creator = uuid4()
    at = datetime.now(UTC)
    saved = dict(
        name="Имя при передаче",
        instagram="https://instagram.com/old/",
        telegram="old_handle",
        phone="saved-phone",
    )
    responses = [
        dict(
            blogger_id=str(creator),
            name="Текущее имя",
            instagram="https://instagram.com/new/",
            telegram="new_handle",
            accepted=True,
            in_offer=True,
            responded_at=at,
            work_state="in_progress",
            ugc_video_url="https://example.test/video",
        )
    ]
    activity = dict(
        currency="RUB",
        refused=[
            dict(
                creator_id=creator,
                name="Текущее имя",
                price=3500,
                reason="Низкая цена",
            )
        ],
    )
    transfers = dict(
        count=15,
        needed=10,
        can_send=True,
        candidates=[
            dict(
                creator_id=creator,
                name="Текущее имя",
                source="Новая цена",
                price=3500,
                state="sent",
            )
        ],
        history=[
            dict(
                creator_id=creator,
                contact=saved,
                source="counteroffer",
                requested_price=3500,
                sent_at=at,
                feedback="worked",
            )
        ],
    )
    workspace = creator_workspace(responses, activity, transfers)
    (row,) = workspace["rows"]
    assert row["name"] == "Имя при передаче"
    assert row["contact"] == saved
    assert row["current_contact"]["telegram"] == "new_handle"
    assert row["group"] == "delivered" and not row["can_send"]
    assert row["response"] == "Новая цена" and row["price"] == 3500
    assert row["work"] == "В работе" and row["feedback"] == "worked"
    assert row["video"] == "https://example.test/video"
    assert {f["key"]: f["count"] for f in workspace["filters"]} == dict(
        all=1, delivered=1, reserve=0, price=0, declined=0, selected=0
    )


@pytest.mark.parametrize(
    "state", [None, "failed", "unknown", "sending", "sent"]
)
@pytest.mark.parametrize("can_send", [True, False])
def test_workspace_preserves_existing_retry_and_closed_order_gates(
    state, can_send
):
    creator = uuid4()
    transfers = dict(
        count=0,
        needed=10,
        can_send=can_send,
        history=[],
        candidates=[
            dict(creator_id=creator, name=None, source="Резерв", state=state)
        ],
    )
    (row,) = creator_workspace([], transfers=transfers)["rows"]
    assert row["group"] == "reserve" and row["response"] == "Согласен"
    assert row["can_send"] is (can_send and state in (None, "failed"))


def test_workspace_distinguishes_same_names_and_unsent_prices_from_refusals():
    selected, reserve, price, refused, historical = (uuid4() for _ in range(5))
    responses = [
        dict(
            blogger_id=str(selected), name="Анна", in_offer=True, accepted=True
        ),
        dict(
            blogger_id=str(reserve), name="Анна", in_offer=False, accepted=True
        ),
    ]
    activity = dict(
        currency="USD",
        refused=[
            dict(
                creator_id=price, name=None, price=4096.02, reason="Низкая цена"
            ),
            dict(
                creator_id=refused,
                name="Автор отказа",
                price=None,
                reason="Нет времени",
            ),
        ],
    )
    transfers = dict(
        count=1,
        needed=10,
        can_send=True,
        candidates=[
            dict(
                creator_id=price,
                name="Новая цена",
                source="Новая цена",
                price=4096.02,
                state=None,
            )
        ],
        history=[
            dict(
                creator_id=historical,
                contact={"username": "Архивное имя"},
                source="replacement",
                sent_at=None,
            )
        ],
    )
    workspace = creator_workspace(
        responses,
        activity,
        transfers,
        {str(refused): dict(name="Автор отказа", telegram="refusal_handle")},
        offer_price=1000,
    )
    rows = {row["creator_id"]: row for row in workspace["rows"]}
    assert len(rows) == 5
    assert rows[str(selected)]["group"] == "selected"
    assert rows[str(reserve)]["group"] == "reserve"
    assert rows[str(price)]["group"] == "price"
    assert rows[str(refused)]["group"] == "declined"
    assert rows[str(historical)]["name"] == "Архивное имя"
    assert rows[str(historical)]["response"] == "Согласен"
    assert rows[str(refused)]["contact"]["telegram"] == "refusal_handle"
    assert workspace["currency"] == "USD" and workspace["offer_price"] == 1000


def test_workspace_has_safe_empty_and_legacy_fallback():
    empty = creator_workspace([])
    assert empty["rows"] == [] and empty["transfer_count"] is None
    assert all(f["count"] == 0 for f in empty["filters"])
    creator = uuid4()
    (row,) = creator_workspace(
        [dict(blogger_id=str(creator), in_offer=True, assigned_at="saved-time")]
    )["rows"]
    assert row["response"] == "Назначен" and row["responded_at"] == "saved-time"


def test_paid_assignment_waits_for_normal_delivery_not_manual_handoff():
    creator = uuid4()
    transfers = dict(
        count=0,
        needed=10,
        can_send=True,
        history=[],
        candidates=[dict(creator_id=creator, source="Резерв", state=None)],
    )
    (row,) = creator_workspace(
        [dict(blogger_id=str(creator), in_offer=True)], transfers=transfers
    )["rows"]
    assert row["in_offer"] and row["group"] == "selected"
    assert not row["can_send"]


@pytest.mark.parametrize("source", ["reserve", "counteroffer"])
@pytest.mark.parametrize("current_price", [None, 5000])
def test_workspace_distinguishes_offer_price_and_preserves_changed_quote(
    source, current_price
):
    creator = uuid4()
    transfers = dict(
        count=1,
        needed=10,
        can_send=True,
        candidates=[],
        history=[
            dict(
                creator_id=creator,
                contact={"name": "Автор"},
                source=source,
                requested_price=3000,
            )
        ],
    )
    activity = dict(
        refused=[
            dict(creator_id=creator, price=current_price, reason="Низкая цена")
        ]
        if current_price is not None
        else []
    )
    (row,) = creator_workspace([], activity, transfers)["rows"]
    assert row["price"] == (current_price or 3000)
    assert row["delivered_price"] == 3000
    assert row["price_proposed"] is (
        current_price is not None or source == "counteroffer"
    )
