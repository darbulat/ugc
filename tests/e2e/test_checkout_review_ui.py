"""Admin reconciliation runs inside the signed Telegram Mini App."""

from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import MiniAppNetwork, open_app

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
ORDER = "41500000-0000-4000-8000-000000000001"
AUTHORIZATION = "41500000-0000-4000-8000-000000000002"
PREFIX = "/miniapp/api/financial/checkout/"


@pytest.mark.parametrize("case", ["unpaid", "not_admin", "receipt_received"])
def test_checkout_review_link_and_admin_confirmation(page, case):
    class ReviewNetwork(MiniAppNetwork):
        def __init__(self):
            super().__init__(registered=True)
            self.review = []

        def route(self, route):
            path = urlsplit(route.request.url).path
            if not path.startswith(PREFIX):
                super().route(route)
                return
            body = route.request.post_data_json
            assert body["init_data"] == "synthetic-test-auth"
            assert body["platform"] == "telegram"
            if path == f"{PREFIX}orders/{ORDER}/review-context":
                if case == "not_admin":
                    route.fulfill(status=403, json={"detail": "denied"})
                    return
                route.fulfill(
                    json={
                        "order_id": ORDER,
                        "amount_minor": 500000,
                        "currency": "RUB",
                        "order_open_for_payment": True,
                        "capture_state": "not_recorded",
                        "paid_receipt_count": int(case == "receipt_received"),
                        "authorization_id": None
                        if self.review
                        else AUTHORIZATION,
                        "version": 3,
                    }
                )
                return
            assert path == f"{PREFIX}authorizations/{AUTHORIZATION}/review"
            self.review.append(body)
            route.fulfill(json={"review_id": str(uuid4())})

    network = ReviewNetwork()
    errors = open_app(page, network, start_param=f"payreview_{UUID(ORDER).hex}")
    dialog = page.get_by_role("dialog", name="Сверка оплаты")
    expect(dialog).to_be_visible()
    submit = dialog.get_by_role("button", name="Закрыть авторизацию")
    if case != "unpaid":
        status = (
            "действующим входом" if case == "not_admin" else "Проверьте статус"
        )
        expect(dialog.get_by_role("status")).to_contain_text(status)
        expect(submit).to_be_hidden()
        assert not network.review
    else:
        expect(dialog.get_by_role("status")).to_contain_text("5\xa0000")
        dialog.get_by_label("ID операции", exact=False).fill("synthetic-ks-123")
        submit.click()
        assert not network.review
        dialog.get_by_role("checkbox").check()
        submit.click()
        expect(dialog.get_by_role("status")).to_contain_text("закрыта")
        expect(submit).to_be_hidden()
        [body] = network.review
        assert body["expected_version"] == 3
        assert body["evidence_reference"] == "synthetic-ks-123"
        assert body["decision"] == "confirmed_not_charged"
    assert not errors
