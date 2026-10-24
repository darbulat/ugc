"""Corrections UI runs against a synthetic signed boundary, never live money."""

from copy import deepcopy
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import (
    MiniAppNetwork,
    open_app,
    screenshot,
)

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
ACTOR = "10000000-0000-4000-8000-000000000001"
ORDER = "10000000-0000-4000-8000-000000000002"
ITEM = "10000000-0000-4000-8000-000000000003"
CASE = "10000000-0000-4000-8000-000000000004"
INTENT = "10000000-0000-4000-8000-000000000005"
OBSERVATION = "10000000-0000-4000-8000-000000000006"
AT = "2026-10-24T12:00:00Z"
HASH = "a" * 64


def case_detail():
    return {
        "case_id": CASE,
        "order_id": ORDER,
        "paid_item_ids": [ITEM],
        "total_minor": "50000",
        "currency": "RUB",
        "recorded_at": AT,
        "current": {
            "case_id": CASE,
            "version": 1,
            "source_hash": HASH,
            "request_status": "requested",
            "review_status": "pending",
            "match_status": "unmatched",
            "application_status": "unapplied",
            "observation_ids": [],
            "blockers": [],
        },
        "state_unavailable": False,
        "allowed_actions": ["review", "record_observation", "match"],
        "request": {
            "reason": "<img src=x onerror=alert(1)>",
            "recorded_at": AT,
        },
        "events": [],
        "intents": [{"id": INTENT, "intent_id": INTENT}],
        "observations": [
            {
                "id": OBSERVATION,
                "observation_id": OBSERVATION,
                "amount_minor": "50000",
                "currency": "RUB",
                "bank_reference": "SYNTHETIC-PRIVATE-REFERENCE",
            }
        ],
        "matches": [],
    }


class CorrectionsNetwork(MiniAppNetwork):
    def __init__(self, *, admin=False, locale="ru"):
        super().__init__(
            locale if locale in ("ru", "en", "kk") else "ru", registered=True
        )
        self.ui_locale = locale
        self.admin = admin
        self.entries = []
        self.lost = False
        self.held = []
        self.hold_detail = False
        self.recorded = None
        self.current = case_detail()
        self.list_error = False
        self.hold_list = False
        self.paused = False
        self.preview_allowed = True
        self.preview_total = "50000"
        self.unavailable_observation = False
        self.orders_error = False
        self.hold_paths = set()
        self.command_failures = []

    def route(self, route):  # noqa: PLR0912
        path = urlparse(route.request.url).path
        if path.endswith("/me") and self.ui_locale in ("be", "uz"):
            route.fulfill(
                json={
                    "locale": self.ui_locale,
                    "country": "ru",
                    "has_advertiser_profile": True,
                }
            )
            return
        if "/financial/corrections/" not in path:
            super().route(route)
            return
        body = route.request.post_data_json
        self.requests.append((path, deepcopy(body)))
        suffix = path.split("/financial/corrections", 1)[1]
        if (
            suffix
            in (
                "/request",
                "/admin/review",
                "/admin/observation",
                "/admin/match",
            )
            and self.command_failures
        ):
            failure = self.command_failures.pop(0)
            if failure == "abort":
                route.abort("failed")
            else:
                route.fulfill(
                    status=failure,
                    json={"detail": "correction_source_conflict"},
                )
            return
        if suffix in self.hold_paths:
            self.held.append(route)
            return
        if suffix == "/context":
            data = {
                "actor_id": ACTOR,
                "admin": self.admin,
                "as_of": AT,
                "writes_paused": self.paused,
                "capabilities": {
                    "read_own_cases": True,
                    "read_admin_queue": self.admin,
                    "request": True,
                    "review": self.admin,
                    "record_observation": self.admin,
                    "match": self.admin,
                },
            }
        elif suffix in ("/list", "/admin/queue"):
            if self.list_error:
                route.fulfill(
                    status=503, json={"detail": "correction_unavailable"}
                )
                return
            if self.hold_list:
                self.held.append(route)
                return
            data = {
                "entries": self.entries,
                "has_more": False,
                "next_cursor": None,
                "as_of": AT,
            }
        elif suffix == "/orders":
            if self.orders_error:
                route.fulfill(
                    status=503, json={"detail": "correction_unavailable"}
                )
                return
            data = {
                "entries": [
                    {
                        "order_id": ORDER,
                        "title": "Synthetic order",
                        "items": [
                            {
                                "paid_item_id": ITEM,
                                "ordinal": 1,
                                "selection_state": "pending",
                                "selection_due_at": AT,
                            }
                        ],
                    }
                ],
                "has_more": False,
            }
        elif suffix == "/preview":
            data = {
                "order_id": ORDER,
                "paid_item_ids": [ITEM],
                "existing_case_id": body.get("existing_case_id"),
                "source_hash": HASH,
                "total_minor": self.preview_total,
                "currency": "RUB",
                "components": [
                    {
                        "paid_item_id": ITEM,
                        "gross_minor": "50000",
                        "selection_due_at": AT,
                    }
                ],
                "blockers": []
                if self.preview_allowed
                else ["correction_selection_not_due"],
                "can_request": True,
                "can_approve": self.preview_allowed,
                "as_of": AT,
            }
        elif suffix == f"/{CASE}/detail":
            if self.hold_detail:
                self.held.append(route)
                return
            data = self.current
        elif suffix == "/operations/status":
            data = {
                "recorded": self.recorded is not None,
                "original_result": self.recorded,
                "current": self.current["current"]
                if self.recorded and not self.unavailable_observation
                else None,
            }
        else:
            data = deepcopy(self.current["current"])
            data["applied"] = False
            if suffix == "/admin/match":
                data.update(
                    match_status="matched",
                    application_status="awaiting_assessment",
                    blockers=["correction_compensation_assessment_required"],
                )
                self.current["current"].update(
                    match_status="matched",
                    application_status="awaiting_assessment",
                    blockers=["correction_compensation_assessment_required"],
                )
            if suffix == "/admin/observation":
                data["observation_id"] = OBSERVATION
                data["intent_id"] = INTENT
                if self.unavailable_observation:
                    data = {
                        "case_id": CASE,
                        "observation_id": OBSERVATION,
                        "intent_id": INTENT,
                        "state_unavailable": True,
                        "blockers": ["correction_state_unavailable"],
                        "applied": False,
                    }
            self.recorded = deepcopy(data)
            self.entries = [self.current]
            if self.lost:
                self.lost = False
                route.abort("failed")
                return
        route.fulfill(json=data)


@pytest.fixture(autouse=True)
def short_actions(page):
    page.set_default_timeout(3000)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_manager_opens_cases_from_own_dashboard_and_returns(page, platform):
    network = CorrectionsNetwork()
    network.registered = False
    network.manager = True
    errors = open_app(page, network, platform)
    page.locator("#btn-manager-role").click()
    expect(page.locator("#screen-manager-orders")).to_be_visible()
    page.locator("#screen-manager-orders [data-corrections-open]").click()
    expect(page.locator("#screen-corrections")).to_be_visible()
    expect(page.locator("#correction-list")).to_contain_text(
        "Обращений пока нет."
    )
    page.locator("#correction-back").click()
    expect(page.locator("#screen-manager-orders")).to_be_visible()
    assert not errors


def enter(page, network, platform="telegram", *, native=False):
    errors = open_app(page, network, platform, native=native)
    page.locator("#screen-advertiser-dashboard [data-corrections-open]").click()
    expect(page.locator("#screen-corrections")).to_be_visible()
    expect(page.locator("#correction-new")).to_have_count(1)
    expect(page.locator("#screen-corrections")).to_have_attribute(
        "aria-busy", "false"
    )
    return errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("locale", ["ru", "en", "kk", "be", "uz"])
def test_owner_preview_and_exact_request(page, platform, locale):
    page.set_viewport_size({"width": 320, "height": 780})
    network = CorrectionsNetwork(locale=locale)
    errors = enter(page, network, platform)
    page.locator("#correction-new").click()
    page.locator("[data-correction-order]").click()
    page.locator("[data-correction-item]").check()
    page.locator("#correction-preview").click()
    expect(page.locator("#correction-preview-card")).to_contain_text("500,00")
    page.locator("#correction-request-reason").fill("Synthetic request reason")
    screenshot(page, f"{platform}-{locale}-correction-preview-light")
    page.locator("#correction-request").click()
    expect(page.locator("#correction-receipt")).to_be_visible()
    payload = next(
        body
        for path, body in network.requests
        if path.endswith("/corrections/request")
    )
    assert payload["paid_item_ids"] == [ITEM]
    assert payload["expected_source_hash"] == HASH
    assert payload["reason"] == "Synthetic request reason"
    assert payload["init_data"] == "synthetic-test-auth"
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert not errors


def test_unknown_result_reuses_same_key_without_private_persistence(page):
    network = CorrectionsNetwork()
    network.lost = True
    enter(page, network)
    page.locator("#correction-new").click()
    page.locator("[data-correction-order]").click()
    page.locator("[data-correction-item]").check()
    page.locator("#correction-preview").click()
    page.locator("#correction-request-reason").fill("PRIVATE REQUEST REASON")
    page.locator("#correction-request").click()
    expect(page.locator("#correction-retry")).to_be_visible()
    page.locator("#correction-retry").click()
    expect(page.locator("#correction-receipt")).to_be_visible()
    sends = [
        body
        for path, body in network.requests
        if path.endswith("/corrections/request")
    ]
    assert len(sends) == 2 and sends[0] == sends[1]
    storage = page.evaluate(
        "JSON.stringify({session:{...sessionStorage},local:{...localStorage}})"
    )
    assert "PRIVATE REQUEST REASON" not in storage
    assert "synthetic-test-auth" not in storage
    page.reload()
    page.locator("#screen-advertiser-dashboard [data-corrections-open]").click()
    expect(page.locator("#correction-receipt")).to_be_visible()
    assert (
        len(
            [
                p
                for p, _ in network.requests
                if p.endswith("/corrections/request")
            ]
        )
        == 2
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_exact_observation_and_match_wait_for_assessment(page, platform):
    page.set_viewport_size({"width": 320, "height": 780})
    network = CorrectionsNetwork(admin=True)
    network.entries = [network.current]
    errors = enter(page, network, platform)
    page.locator("#correction-admin").click()
    page.locator("[data-correction-case]").click()
    expect(page.locator("#correction-detail")).to_contain_text(
        "<img src=x onerror=alert(1)>"
    )
    assert page.locator("#correction-detail img").count() == 0
    page.locator("#correction-observe").click()
    page.locator("#correction-observation-reason").fill(
        "Synthetic actual observation"
    )
    page.locator("#correction-bank-reference").fill("PRIVATE BANK REFERENCE")
    page.locator("#correction-observation-amount").fill("-9007199254740993")
    page.locator("#correction-currency").fill("RUB")
    page.locator("#correction-evidence-reference").fill("PRIVATE EVIDENCE")
    page.locator("#correction-evidence-hash").fill(HASH)
    page.locator("#correction-record").click()
    expect(page.locator("#correction-receipt")).to_be_visible()
    observed = next(
        body
        for path, body in network.requests
        if path.endswith("/admin/observation")
    )
    assert observed["amount_minor"] == "-9007199254740993"
    assert observed["currency"] == "RUB"
    assert "PRIVATE BANK REFERENCE" not in page.evaluate(
        "JSON.stringify({...sessionStorage})"
    )
    page.locator("#correction-done").click()
    page.locator("#correction-admin").click()
    page.locator("[data-correction-case]").click()
    page.locator("#correction-match").click()
    page.locator("#correction-match-reason").fill("Synthetic matching reason")
    page.locator("#correction-evidence-reference").fill("Synthetic evidence")
    page.locator("#correction-evidence-hash").fill(HASH)
    page.locator("#correction-confirm-match").click()
    expect(
        page.locator(
            "#correction-receipt [data-correction-state=awaiting_assessment]"
        )
    ).to_be_visible()
    expect(
        page.locator(
            "#correction-current [data-correction-state=awaiting_assessment]"
        )
    ).to_be_visible()
    screenshot(page, f"{platform}-correction-awaiting-assessment")
    assert not errors


def test_late_detail_does_not_reopen_screen_or_expose_admin_data(page):
    network = CorrectionsNetwork(admin=True)
    network.entries = [network.current]
    enter(page, network)
    network.hold_detail = True
    page.locator("[data-correction-case]").click()
    expect(page.locator("#correction-back")).to_be_visible()
    page.locator("#correction-back").click()
    page.locator("#correction-back").click()
    expect(page.locator("#screen-advertiser-dashboard")).to_be_visible()
    for held in network.held:
        held.fulfill(json=network.current)
    expect(page.locator("#screen-advertiser-dashboard")).to_be_visible()
    assert page.locator("#screen-corrections").inner_text() == ""


def test_list_loading_and_failure_do_not_claim_empty(page):
    network = CorrectionsNetwork()
    network.hold_list = True
    enter(page, network)
    expect(page.locator("#correction-list")).to_contain_text("Загрузка")
    expect(page.locator("#correction-list")).not_to_contain_text(
        "Обращений пока нет"
    )
    for held in network.held:
        held.fulfill(status=503, json={"detail": "correction_unavailable"})
    expect(page.locator("#correction-list")).to_contain_text("Не удалось")
    expect(page.locator("#correction-list")).not_to_contain_text(
        "Обращений пока нет"
    )


@pytest.mark.parametrize("allowed", [False, True])
def test_admin_review_requires_fresh_eligibility_preview(page, allowed):
    network = CorrectionsNetwork(admin=True)
    network.preview_allowed = allowed
    network.entries = [network.current]
    enter(page, network)
    page.locator("#correction-admin").click()
    page.locator("[data-correction-case]").click()
    page.locator("#correction-review").click()
    expect(page.locator("#correction-approve")).to_be_disabled()
    page.locator("#correction-review-preview").click()
    expect(page.locator("#correction-review-preview-card")).to_be_visible()
    if allowed:
        expect(page.locator("#correction-approve")).to_be_enabled()
    else:
        expect(page.locator("#correction-approve")).to_be_disabled()
        expect(page.locator("#correction-review-preview-card")).to_contain_text(
            "Срок подбора"
        )
    page.locator("#correction-review-reason").fill("Synthetic decision")
    page.locator("#correction-evidence-reference").fill("Synthetic evidence")
    page.locator("#correction-evidence-hash").fill(HASH)
    page.locator(
        "#correction-approve" if allowed else "#correction-reject"
    ).click()
    expect(page.locator("#correction-receipt")).to_be_visible()
    sent = next(
        body
        for path, body in network.requests
        if path.endswith("/admin/review")
    )
    assert sent["decision"] == ("approve" if allowed else "reject")
    assert (
        sent["expected_version"] == 1 and sent["expected_source_hash"] == HASH
    )


def test_recorded_unknown_amount_can_finish_without_current_state(
    page,
):
    network = CorrectionsNetwork(admin=True)
    network.unavailable_observation = True
    enter(page, network)
    page.locator("#correction-new-observation").click()
    page.locator("#correction-observation-reason").fill(
        "Synthetic actual unknown amount"
    )
    page.locator("#correction-bank-reference").fill("Synthetic bank reference")
    page.locator("#correction-currency").fill("")
    page.locator("#correction-evidence-reference").fill("Synthetic evidence")
    page.locator("#correction-evidence-hash").fill(HASH)
    page.locator("#correction-record").click()
    expect(page.locator("#correction-done")).to_be_enabled()
    sent = next(
        body
        for path, body in network.requests
        if path.endswith("/admin/observation")
    )
    assert sent["amount_minor"] is None and sent["currency"] is None
    assert sent["case_id"] is None and sent["expected_version"] is None
    page.locator("#correction-done").click()
    expect(page.locator("#correction-new")).to_be_visible()


@pytest.mark.parametrize(
    "amount",
    [
        "-0",
        "+1",
        "01",
        "1.5",
        "1e3",
        "9223372036854775808",
        "-9223372036854775809",
    ],
)
def test_observation_rejects_inexact_or_out_of_range_minor_units(page, amount):
    network = CorrectionsNetwork(admin=True)
    enter(page, network)
    page.locator("#correction-new-observation").click()
    page.locator("#correction-observation-reason").fill(
        "Synthetic actual report"
    )
    page.locator("#correction-bank-reference").fill("Synthetic bank reference")
    page.locator("#correction-evidence-reference").fill("Synthetic evidence")
    page.locator("#correction-evidence-hash").fill(HASH)
    page.locator("#correction-observation-amount").fill(amount)
    page.locator("#correction-record").click()
    expect(page.locator("#correction-error")).to_contain_text("точный формат")
    assert not any(
        path.endswith("/admin/observation") for path, _ in network.requests
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_native_dark_keyboard_and_owner_projection(page, platform):
    network = CorrectionsNetwork()
    network.entries = [network.current]
    errors = enter(page, network, platform, native=True)
    page.set_viewport_size({"width": 320, "height": 780})
    page.evaluate(
        "window.__host.wa.colorScheme='dark';window.__host.events.themeChanged()"
    )
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    page.locator("[data-correction-case]").click()
    expect(page.locator("#correction-detail")).to_contain_text("Запрос подан")
    expect(page.locator("#correction-detail")).not_to_contain_text(
        "SYNTHETIC-PRIVATE-REFERENCE"
    )
    expect(page.locator("#correction-observe")).to_have_count(0)
    screenshot(page, f"{platform}-correction-owner-dark")
    page.evaluate("window.__host.wa.BackButton.click()")
    page.evaluate("window.__host.wa.MainButton.click()")
    page.locator("[data-correction-order]").click()
    page.locator("[data-correction-item]").check()
    page.evaluate("window.__host.wa.MainButton.click()")
    page.locator("#correction-request-reason").fill("Synthetic keyboard reason")
    page.locator("#correction-request-reason").focus()
    page.keyboard.press("Tab")
    page.evaluate("window.__host.wa.MainButton.click()")
    expect(page.locator("#correction-receipt")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert not errors


def test_own_early_case_can_attach_request_for_exact_existing_subset(page):
    network = CorrectionsNetwork()
    network.current["allowed_actions"] = ["request"]
    network.current["current"]["request_status"] = "none"
    network.current["request"] = None
    network.current["paid_item_ids"] = []
    network.current["available_items"] = [
        {
            "paid_item_id": ITEM,
            "ordinal": 1,
            "selection_state": "pending",
            "selection_due_at": AT,
        }
    ]
    network.entries = [network.current]
    enter(page, network)
    page.locator("[data-correction-case]").click()
    page.locator("#correction-attach-request").click()
    expect(page.locator("[data-correction-item]")).not_to_be_checked()
    page.locator("[data-correction-item]").check()
    page.locator("#correction-preview").click()
    page.locator("#correction-request-reason").fill(
        "Synthetic own existing case request"
    )
    page.locator("#correction-request").click()
    expect(page.locator("#correction-receipt")).to_be_visible()
    sent = next(
        body
        for path, body in network.requests
        if path.endswith("/corrections/request")
    )
    assert sent["existing_case_id"] == CASE and sent["paid_item_ids"] == [ITEM]


@pytest.mark.parametrize("currency", [None, "JPY"])
def test_admin_unknown_currency_keeps_exact_minor_units(page, currency):
    network = CorrectionsNetwork(admin=True)
    network.current["observations"][0].update(
        amount_minor="-9007199254740993", currency=currency
    )
    network.entries = [network.current]
    page.set_viewport_size({"width": 320, "height": 780})
    enter(page, network)
    page.locator("#correction-admin").click()
    page.locator("[data-correction-case]").click()
    expect(page.locator("#correction-detail")).to_contain_text(
        "-9007199254740993 минимальных единиц валюты"
    )
    expect(page.locator("#correction-detail")).to_contain_text(
        "Неизвестно" if currency is None else "JPY"
    )
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_paused_core_disables_request_but_can_record_actual_observation(page):
    network = CorrectionsNetwork(admin=True)
    network.paused = True
    enter(page, network)
    expect(page.locator("#correction-new")).to_be_disabled()
    expect(page.locator("#correction-new-observation")).to_be_enabled()
    expect(page.locator("#screen-corrections")).to_contain_text(
        "приостановлены"
    )


def test_unknown_status_and_blocker_are_localized_without_raw_backend_codes(
    page,
):
    network = CorrectionsNetwork()
    network.current["current"].update(
        application_status="unknown_future_backend_code",
        blockers=["internal_unknown_blocker"],
    )
    network.entries = [network.current]
    enter(page, network)
    page.locator("[data-correction-case]").click()
    expect(page.locator("#correction-detail")).to_contain_text(
        "Требуется проверка"
    )
    expect(page.locator("#correction-detail")).not_to_contain_text(
        "unknown_future_backend_code"
    )
    expect(page.locator("#correction-detail")).not_to_contain_text(
        "internal_unknown_blocker"
    )


def test_native_session_change_discards_private_late_detail(page):
    network = CorrectionsNetwork(admin=True)
    network.entries = [network.current]
    enter(page, network)
    network.hold_detail = True
    with page.expect_request(
        lambda request: urlparse(request.url).path.endswith(
            f"/financial/corrections/{CASE}/detail"
        )
    ):
        page.locator("[data-correction-case]").click()
    assert len(network.held) == 1
    page.evaluate("window.__host.wa.initData='synthetic-changed-session'")
    for held in network.held:
        held.fulfill(json=network.current)
    expect(page.locator("#screen-corrections")).not_to_contain_text(
        "SYNTHETIC-PRIVATE-REFERENCE"
    )
    expect(page.locator("#correction-detail")).to_have_count(0)
    expect(page.locator("#screen-corrections")).to_be_empty()
    assert not any(
        path.endswith("/admin/observation") for path, _ in network.requests
    )


def test_source_blocked_request_retained_without_claiming_known_amount(page):
    network = CorrectionsNetwork()
    network.preview_allowed = False
    network.preview_total = None
    enter(page, network)
    page.locator("#correction-new").click()
    page.locator("[data-correction-order]").click()
    page.locator("[data-correction-item]").check()
    page.locator("#correction-preview").click()
    expect(page.locator("#correction-preview-card")).to_contain_text(
        "Сумма неизвестна"
    )
    expect(page.locator("#correction-preview-card")).to_contain_text(
        "Срок подбора ещё не наступил"
    )
    page.locator("#correction-request-reason").fill(
        "Synthetic review request despite blocker"
    )
    page.locator("#correction-request").click()
    expect(page.locator("#correction-receipt")).to_be_visible()
    sent = next(
        body
        for path, body in network.requests
        if path.endswith("/corrections/request")
    )
    assert "amount_minor" not in sent


@pytest.mark.parametrize("bad_amount", [50000, "050000", "50000.0"])
def test_invalid_money_transport_does_not_create_reviewable_preview(
    page, bad_amount
):
    network = CorrectionsNetwork()
    network.preview_total = bad_amount
    enter(page, network)
    page.locator("#correction-new").click()
    page.locator("[data-correction-order]").click()
    page.locator("[data-correction-item]").check()
    page.locator("#correction-preview").click()
    expect(page.locator("#correction-error")).to_contain_text("Не удалось")
    expect(page.locator("#correction-request")).to_have_count(0)


def visibility(page, hidden):
    page.evaluate(
        """hidden => {
            Object.defineProperty(document, 'hidden', {
                configurable: true, get: () => hidden
            });
            document.dispatchEvent(new Event('visibilitychange'));
        }""",
        hidden,
    )


@pytest.mark.parametrize("admin_review", [False, True])
def test_hidden_preview_cancels_read_and_can_be_retried(page, admin_review):
    network = CorrectionsNetwork(admin=admin_review)
    network.entries = [network.current]
    enter(page, network)
    if admin_review:
        page.locator("#correction-admin").click()
        page.locator("[data-correction-case]").click()
        page.locator("#correction-review").click()
        preview_id = "#correction-review-preview"
        card_id = "#correction-review-preview-card"
    else:
        page.locator("#correction-new").click()
        page.locator("[data-correction-order]").click()
        page.locator("[data-correction-item]").check()
        preview_id = "#correction-preview"
        card_id = "#correction-preview-card"
    network.hold_paths.add("/preview")
    page.locator(preview_id).click()
    expect(page.locator("#screen-corrections")).to_have_attribute(
        "aria-busy", "true"
    )
    visibility(page, True)
    visibility(page, False)
    expect(page.locator("#screen-corrections")).to_have_attribute(
        "aria-busy", "false"
    )
    for held in network.held:
        held.fulfill(status=503, json={"detail": "correction_unavailable"})
    expect(page.locator(card_id)).to_have_count(0)
    if admin_review:
        page.locator("#correction-review").click()
    network.hold_paths.clear()
    page.locator(preview_id).click()
    expect(page.locator(card_id)).to_be_visible()
    assert not any(
        path.endswith("/admin/review") or path.endswith("/corrections/request")
        for path, _ in network.requests
    )


def test_order_source_failure_can_retry_without_claiming_empty(page):
    network = CorrectionsNetwork()
    network.orders_error = True
    enter(page, network)
    page.locator("#correction-new").click()
    expect(page.locator("#correction-orders")).to_contain_text("Не удалось")
    expect(page.locator("#correction-orders")).not_to_contain_text(
        "Обращений пока нет"
    )
    expect(page.locator("#correction-orders-retry")).to_be_enabled()
    network.orders_error = False
    page.locator("#correction-orders-retry").click()
    expect(page.locator("[data-correction-order]")).to_be_visible()


@pytest.mark.parametrize("kind", ["orders", "detail"])
def test_hidden_detail_or_orders_can_retry_cancelled_read(page, kind):
    network = CorrectionsNetwork()
    network.entries = [network.current]
    enter(page, network)
    path = "/orders" if kind == "orders" else f"/{CASE}/detail"
    network.hold_paths.add(path)
    page.locator(
        "#correction-new" if kind == "orders" else "[data-correction-case]"
    ).click()
    expect(page.locator("#screen-corrections")).to_have_attribute(
        "aria-busy", "true"
    )
    visibility(page, True)
    visibility(page, False)
    expect(page.locator("#screen-corrections")).to_have_attribute(
        "aria-busy", "false"
    )
    retry = page.locator(f"#correction-{kind}-retry")
    expect(retry).to_be_enabled()
    for held in network.held:
        held.fulfill(status=503, json={"detail": "correction_unavailable"})
    network.hold_paths.clear()
    retry.click()
    expect(
        page.locator(
            "[data-correction-order]"
            if kind == "orders"
            else "#correction-detail [data-correction-state=requested]"
        )
    ).to_be_visible()


def test_hidden_pending_command_does_not_unlock_retry_or_duplicate_send(page):
    network = CorrectionsNetwork()
    enter(page, network)
    page.locator("#correction-new").click()
    page.locator("[data-correction-order]").click()
    page.locator("[data-correction-item]").check()
    page.locator("#correction-preview").click()
    page.locator("#correction-request-reason").fill("Synthetic request")
    network.hold_paths.add("/request")
    page.locator("#correction-request").click()
    visibility(page, True)
    visibility(page, False)
    expect(page.locator("#screen-corrections")).to_have_attribute(
        "aria-busy", "true"
    )
    expect(page.locator("#correction-retry")).to_be_disabled()
    expect(page.locator("#correction-check")).to_be_disabled()
    expect(page.locator("#correction-new")).to_have_count(0)
    assert (
        len(
            [
                path
                for path, _ in network.requests
                if path.endswith("/corrections/request")
            ]
        )
        == 1
    )
    network.recorded = deepcopy(network.current["current"])
    for held in network.held:
        held.fulfill(json=network.recorded)
    expect(page.locator("#correction-receipt")).to_be_visible()


def test_changed_native_auth_clears_all_old_private_case_dom(page):
    network = CorrectionsNetwork(admin=True)
    network.entries = [network.current]
    enter(page, network)
    page.locator("#correction-admin").click()
    page.locator("[data-correction-case]").click()
    expect(page.locator("#correction-detail")).to_contain_text(
        "SYNTHETIC-PRIVATE-REFERENCE"
    )
    page.evaluate("window.__host.wa.initData='synthetic-new-principal'")
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    expect(page.locator("#screen-corrections")).to_be_empty()


def test_hidden_case_list_read_can_refresh_after_cancellation(page):
    network = CorrectionsNetwork()
    network.hold_list = True
    enter(page, network)
    expect(page.locator("#correction-list")).to_contain_text("Загрузка")
    visibility(page, True)
    visibility(page, False)
    expect(page.locator("#correction-list")).to_contain_text("Не удалось")
    for held in network.held:
        held.fulfill(status=503, json={"detail": "correction_unavailable"})
    network.hold_list = False
    network.entries = [network.current]
    page.locator("#correction-refresh").click()
    expect(page.locator("[data-correction-case]")).to_be_visible()


def prepare_request(page):
    page.locator("#correction-new").click()
    page.locator("[data-correction-order]").click()
    page.locator("[data-correction-item]").check()
    page.locator("#correction-preview").click()
    page.locator("#correction-request-reason").fill(
        "Synthetic explicit request"
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_first_atomic_conflict_allows_fresh_explicit_request(page, platform):
    network = CorrectionsNetwork()
    network.command_failures = [409]
    enter(page, network, platform)
    prepare_request(page)
    page.locator("#correction-request").click()
    expect(page.locator("#correction-new")).to_be_enabled()
    expect(page.locator("#correction-pending")).to_have_count(0)
    expect(page.locator("#correction-error")).to_contain_text(
        "Данные изменились"
    )
    assert network.recorded is None
    sends = [
        body
        for path, body in network.requests
        if path.endswith("/corrections/request")
    ]
    assert len(sends) == 1
    prepare_request(page)
    page.locator("#correction-request").click()
    expect(page.locator("#correction-receipt")).to_be_visible()
    sends = [
        body
        for path, body in network.requests
        if path.endswith("/corrections/request")
    ]
    assert len(sends) == 2
    assert sends[0]["operation_key"] != sends[1]["operation_key"]


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_unknown_then_retry_conflict_keeps_original_operation(page, platform):
    network = CorrectionsNetwork()
    network.command_failures = ["abort", 409]
    enter(page, network, platform)
    prepare_request(page)
    page.locator("#correction-request").click()
    expect(page.locator("#correction-retry")).to_be_enabled()
    before = page.evaluate("JSON.stringify({...sessionStorage})")
    page.locator("#correction-retry").click()
    expect(page.locator("#correction-retry")).to_be_enabled()
    expect(page.locator("#correction-new")).to_have_count(0)
    assert page.evaluate("JSON.stringify({...sessionStorage})") == before
    sends = [
        body
        for path, body in network.requests
        if path.endswith("/corrections/request")
    ]
    assert len(sends) == 2 and sends[0] == sends[1]


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_restored_unrecorded_operation_stays_blocked(page, platform):
    network = CorrectionsNetwork()
    network.command_failures = ["abort"]
    enter(page, network, platform)
    prepare_request(page)
    page.locator("#correction-request").click()
    expect(page.locator("#correction-retry")).to_be_enabled()
    before = page.evaluate("JSON.stringify({...sessionStorage})")
    page.reload()
    page.locator("#screen-advertiser-dashboard [data-corrections-open]").click()
    expect(page.locator("#correction-check")).to_be_enabled()
    expect(page.locator("#correction-pending")).to_be_visible()
    expect(page.locator("#correction-new")).to_have_count(0)
    expect(page.locator("#correction-retry")).to_have_count(0)
    assert network.recorded is None
    assert page.evaluate("JSON.stringify({...sessionStorage})") == before
    assert (
        len(
            [
                path
                for path, _ in network.requests
                if path.endswith("/corrections/request")
            ]
        )
        == 1
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_first_server_failure_keeps_operation_even_when_not_recorded(
    page, platform
):
    network = CorrectionsNetwork()
    network.command_failures = [503]
    enter(page, network, platform)
    prepare_request(page)
    page.locator("#correction-request").click()
    expect(page.locator("#correction-retry")).to_be_enabled()
    before = page.evaluate("JSON.stringify({...sessionStorage})")
    page.locator("#correction-check").click()
    expect(page.locator("#correction-check")).to_be_enabled()
    expect(page.locator("#correction-new")).to_have_count(0)
    assert network.recorded is None
    assert page.evaluate("JSON.stringify({...sessionStorage})") == before
