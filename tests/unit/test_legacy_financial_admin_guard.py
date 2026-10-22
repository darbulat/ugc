"""Generic SQLAdmin forms must not bypass financial command invariants."""

import pytest

from ugc_bot.admin.app import (
    InteractionAdmin,
    PayoutRequestAdmin,
    ReferralIncomeEntryAdmin,
)


@pytest.mark.parametrize(
    "view", [PayoutRequestAdmin, ReferralIncomeEntryAdmin, InteractionAdmin]
)
def test_financial_rows_have_no_generic_mutation_routes(view):
    assert view.can_create is False
    assert view.can_edit is False
    assert view.can_delete is False


@pytest.mark.asyncio
async def test_generic_interaction_status_update_is_refused_before_any_write(
    monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from sqladmin import ModelView

    import ugc_bot.admin.app as admin_app
    from ugc_bot.domain.enums import InteractionStatus

    old = SimpleNamespace(status=InteractionStatus.ISSUE)
    new = SimpleNamespace(status=InteractionStatus.OK)
    raw_write = AsyncMock(return_value=new)
    monkeypatch.setattr(
        admin_app, "_get_obj_by_pk", AsyncMock(side_effect=[old, new])
    )
    monkeypatch.setattr(admin_app, "_get_admin_container", lambda: None)
    monkeypatch.setattr(ModelView, "update_model", raw_write)
    with pytest.raises(PermissionError, match="audited"):
        await InteractionAdmin().update_model(
            SimpleNamespace(), str(uuid4()), {"status": "ok"}
        )
    raw_write.assert_not_awaited()
