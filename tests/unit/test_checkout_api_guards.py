"""Missing runtime capabilities fail before provider I/O or signed commands."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from tests.application.services.test_checkout_service import setup
from ugc_bot.container.checkout_factory import build_checkout_service
from ugc_bot.miniapp.checkout_api import _service


@pytest.mark.parametrize("case", ["query", "service", "bot"])
def test_checkout_runtime_guard_fails_closed(case):
    checkout, *_ = setup()
    request = SimpleNamespace(
        query_params={"unexpected": "1"} if case == "query" else {},
        app=SimpleNamespace(
            state=SimpleNamespace(
                dispatcher={
                    "checkout_service": None if case == "service" else checkout
                }
            )
        ),
    )
    with pytest.raises(HTTPException) as failure:
        _service(request, gateway=True)
    assert failure.value.status_code == (422 if case == "query" else 503)


def test_checkout_without_transaction_manager_is_not_exposed():
    assert build_checkout_service(object(), None) is None
