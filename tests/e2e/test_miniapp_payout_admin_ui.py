"""Actual TG/MAX admin assets with synthetic hosts and signed API boundaries."""

from copy import deepcopy
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import screenshot
from tests.e2e.test_miniapp_payout_owner_ui import (
    AT,
    DOC,
    HASH,
    REQUEST,
    PayoutNetwork,
    detail,
    enter,
    requirements,
)
from tests.e2e.test_miniapp_payout_owner_ui import (
    review as owner_review,
)

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
OTHER = "20000000-0000-4000-8000-000000000002"
EXECUTION = "20000000-0000-4000-8000-000000000003"
FENCE = "20000000-0000-4000-8000-000000000004"
OUTCOME = "20000000-0000-4000-8000-000000000005"


@pytest.fixture(autouse=True)
def bounded_actions(page):
    page.set_default_timeout(2500)


def publication(version=9):
    return requirements() | {
        "version": version,
        "effective_from": "2099-10-24T12:00:00+03:00",
        "reason": "SYNTHETIC publication reason",
        "legal_reference": "SYNTHETIC legal reference",
        "evidence_reference": "SYNTHETIC evidence reference",
        "actor_id": "10000000-0000-4000-8000-000000000001",
        "recorded_at": AT,
    }


def intent(version=8, provenance="retained_event"):
    return {
        "request_id": REQUEST,
        "execution_id": EXECUTION,
        "fence": FENCE,
        "bank_account": "EXPECTED SYNTHETIC ORIGIN",
        "prepared_at": AT,
        "amount_minor": "9223372036854775807",
        "currency": "RUB",
        "expected_version": version,
        "version_provenance": provenance,
    }


def admin_detail(request_id=REQUEST, state="approved"):
    return detail(state) | {
        "request_id": request_id,
        "version": 8,
        "overdue": True,
        "execution_id": EXECUTION,
        "allowed_actions": [
            "review",
            "reject",
            "start",
            "escalate",
            "reveal_requisites",
            "record_observation",
        ],
        "action_blockers": {},
        "current_execution": intent(8, "current_authority"),
        "observation": {
            "can_record": True,
            "retained_intents": {
                "entries": [intent()],
                "has_more": False,
                "next_cursor": None,
            },
        },
    }


def page_of(entries, cursor=None):
    return {
        "entries": entries,
        "has_more": cursor is not None,
        "next_cursor": cursor,
        "as_of": AT,
    }


class AdminNetwork(PayoutNetwork):
    def __init__(self, locale="en"):
        super().__init__(locale)
        self.context["requirements"] = publication(7) | {
            "effective_from": "2026-10-24T00:00:00Z"
        }
        self.context["latest_publication"] = publication()
        self.context["capabilities"].update(
            read_admin_queue=True,
            read_admin_requirements=True,
            publish_requirements=True,
        )
        self.details = {REQUEST: admin_detail(), OTHER: admin_detail(OTHER)}
        self.queue = page_of(list(self.details.values()), "queue-next")
        self.publications = page_of([publication()], "publication-next")
        self.histories = {
            "events": page_of(
                [
                    {
                        "version": 8,
                        "state": "approved",
                        "reason": "SYNTHETIC event",
                    }
                ],
                "events-next",
            ),
            "intents": page_of([intent() | {"version": 8}]),
            "outcomes": page_of([]),
            "settlements": page_of([]),
        }
        self.lost = set()
        self.response_state = None

    def route(self, route):
        path = urlparse(route.request.url).path.removeprefix("/miniapp/api")
        if "/admin/" not in path:
            return super().route(route)
        body = route.request.post_data_json
        self.requests.append((path, body))
        if path in self.hold:
            self.pending.append((path, route, body))
            return None
        if path in self.errors:
            status, code = self.errors[path]
            route.fulfill(status=status, json={"detail": code})
            return None
        if path in self.lost:
            route.abort()
            return None
        if path == "/payouts/read/admin/queue":
            result = self.queue
        elif path == "/payouts/read/admin/requirements":
            result = self.publications
        elif "/history/" in path:
            result = self.histories[path.rsplit("/", 1)[1]]
        elif path.endswith("/requisites"):
            result = {
                "old_frozen_extra": "SYNTHETIC REVEAL PRIVATE",
                "bank_account": "SYNTHETIC SECRET",
            }
        elif path == "/payouts/admin/command":
            target = {
                "review": "approved",
                "reject": "rejected",
                "start": "executing",
                "escalate": "approved",
            }[body["action"]]
            result = self.details[body["request_id"]] | {
                "state": self.response_state or target,
                "version": 9,
                "fence": FENCE,
            }
            self.details[body["request_id"]] = result
        elif path == "/payouts/admin/result":
            result = self.details[body["request_id"]] | {
                "state": self.response_state or "unknown",
                "version": 9,
            }
            self.details[body["request_id"]] = result
            self.histories["outcomes"] = page_of(
                [
                    {
                        "outcome_id": OUTCOME,
                        "request_id": body["request_id"],
                        "execution_id": body["execution_id"],
                        "status": body["status"],
                        "amount_minor": body["amount_minor"],
                        "currency": body["currency"],
                        "applied": False,
                        "review_reason": "financial_payouts_disabled",
                        "evidence_reference": body["evidence_reference"],
                        "recorded_at": AT,
                    }
                ]
            )
        elif path == "/payouts/admin/requirements/publish":
            result = publication(body["expected_version"] + 1) | body
            self.context["latest_publication"] = result
        else:
            route.fulfill(status=404, json={"detail": "payout_read_not_found"})
            return None
        route.fulfill(json=deepcopy(result))
        return None


def admin_enter(page, network, platform="telegram", mode="queue", **kwargs):
    errors = enter(page, network, platform, **kwargs)
    page.locator(f"#payout-admin-{mode}").click()
    expect(page.locator("#screen-payout-admin")).to_be_visible()
    expect(page.locator("#admin-context")).to_contain_text(AT)
    return errors


def selected(page, network, platform="telegram", **kwargs):
    errors = admin_enter(page, network, platform, **kwargs)
    page.locator("#admin-list button[data-admin-select]").first.click()
    expect(page.locator("#admin-detail")).to_contain_text(REQUEST)
    return errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "queue,requirements_allowed",
    [(True, True), (True, False), (False, True), (False, False)],
)
def test_admin_entries_follow_current_read_capabilities(
    page, platform, queue, requirements_allowed
):
    network = AdminNetwork()
    network.context["capabilities"].update(
        read_admin_queue=queue, read_admin_requirements=requirements_allowed
    )
    enter(page, network, platform)
    assert page.locator("#payout-admin-queue").count() == int(queue)
    assert page.locator("#payout-admin-requirements").count() == int(
        requirements_allowed
    )
    assert not any("/admin/" in p for p, _ in network.requests)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_open_rechecks_context_before_protected_reads(page, platform):
    network = AdminNetwork()
    admin_enter(page, network, platform)
    paths = [p for p, _ in network.requests]
    assert paths.count("/payouts/read/context") == 2
    assert paths.index("/payouts/read/admin/queue") > max(
        i for i, p in enumerate(paths) if p == "/payouts/read/context"
    )
    assert network.requests[-1][1]["limit"] == 20


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_return_preserves_owner_back_target(page, platform):
    network = AdminNetwork()
    admin_enter(page, network, platform)
    page.locator("#admin-back").click()
    expect(page.locator("#payout-balance")).to_be_visible()
    page.locator("#payout-back").click()
    expect(page.locator("#screen-partner")).to_be_visible()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_no_storage_dependency(page, platform):
    network = AdminNetwork()
    admin_enter(page, network, platform)
    page.evaluate(
        "() => { for (const k of ['getItem','setItem','removeItem']) "
        "Storage.prototype[k] = () => { throw Error('storage forbidden'); }; }"
    )
    page.locator("#admin-refresh").click()
    expect(page.locator("#admin-list")).to_contain_text(REQUEST)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_external_departure_and_pagehide_clear_state(page, platform):
    network = AdminNetwork()
    admin_enter(page, network, platform)
    page.evaluate("window.dispatchEvent(new Event('pagehide'))")
    expect(page.locator("#admin-list")).to_be_empty()
    assert EXECUTION not in page.locator("#screen-payout-admin").inner_text()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_queue_uses_bounded_server_order_and_continuation(page, platform):
    network = AdminNetwork()
    admin_enter(page, network, platform)
    expect(page.locator("#admin-list button[data-admin-select]")).to_have_count(
        2
    )
    network.queue = page_of([admin_detail(OTHER, "paid")])
    page.locator("#admin-queue-next").click()
    expect(page.locator("#admin-list button[data-admin-select]")).to_have_count(
        1
    )
    assert [b for p, b in network.requests if p == "/payouts/read/admin/queue"][
        -1
    ]["cursor"] == "queue-next"
    expect(page.locator("#admin-list")).to_contain_text("Paid")


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_detail_A_cannot_replace_selected_B(page, platform):
    network = AdminNetwork()
    path = f"/payouts/read/{REQUEST}/detail"
    network.hold.add(path)
    admin_enter(page, network, platform)
    page.locator("[data-admin-select]").first.click()
    page.locator("[data-admin-select]").nth(1).click()
    expect(page.locator("#admin-detail")).to_contain_text(OTHER)
    next(r for p, r, _ in network.pending if p == path).fulfill(
        json=admin_detail()
    )
    expect(page.locator("#admin-detail")).not_to_contain_text(REQUEST)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_history_cursors_are_request_and_kind_scoped(page, platform):
    network = AdminNetwork()
    selected(page, network, platform)
    page.locator("#admin-history-events").click()
    expect(page.locator("#admin-history-events-page")).to_contain_text(
        "SYNTHETIC event"
    )
    page.locator("#admin-history-events-next").click()
    page.locator("#admin-history-intents").click()
    requests = [(p, b) for p, b in network.requests if "/history/" in p]
    assert requests[1][1]["cursor"] == "events-next"
    assert requests[2][1]["cursor"] is None
    assert all(REQUEST in p and b["limit"] == 20 for p, b in requests)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_demoted_owner_detail_200_is_not_admin_success(page, platform):
    network = AdminNetwork()
    selected(page, network, platform)
    network.details[OTHER] = detail() | {"request_id": OTHER}
    page.locator("[data-admin-select]").nth(1).click()
    expect(page.locator("#admin-error")).to_contain_text("administrator")
    expect(page.locator("#admin-list")).to_be_empty()
    expect(page.locator("#admin-detail")).to_be_empty()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_unavailable_current_state_does_not_erase_retained_history(
    page, platform
):
    network = AdminNetwork()
    network.details[REQUEST].update(
        state="unavailable",
        version=None,
        current_execution=None,
        allowed_actions=["record_observation"],
    )
    selected(page, network, platform)
    page.locator("#admin-history-intents").click()
    expect(page.locator("#admin-history-intents-page")).to_contain_text(
        EXECUTION
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_read_text_is_inert(page, platform):
    network = AdminNetwork()
    network.histories["events"] = page_of(
        [{"reason": '<img src=x onerror="alert(1)">'}]
    )
    selected(page, network, platform)
    page.locator("#admin-history-events").click()
    expect(page.locator("#admin-history-events-page")).to_contain_text("<img")
    assert page.locator("#admin-history img").count() == 0


def publication_draft(page):
    page.locator("#admin-publication-new").click()
    page.locator("#admin-enabled").check()
    page.locator("#admin-effective-from").fill("2099-10-24T12:00:00+03:00")
    page.locator("#admin-reason").fill("SYNTHETIC private publication reason")
    for name in ("legal", "terms", "evidence"):
        page.locator(f"#admin-{name}-reference").fill(f"SYNTHETIC {name}")
    page.locator("#admin-document-text").fill(
        "SYNTHETIC TEST DOCUMENT\n\nLiteral <img src=x>"
    )
    page.locator("#admin-source-locale").fill("ru")
    import json

    page.locator("#admin-field-definitions").fill(
        json.dumps(requirements()["field_definitions"])
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_latest_future_publication_is_distinct_from_effective(
    page, platform
):
    network = AdminNetwork()
    admin_enter(page, network, platform, mode="requirements")
    expect(page.locator("#admin-effective")).to_contain_text("7")
    expect(page.locator("#admin-latest")).to_contain_text("9")


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_publication_exact_document_and_field_schema(page, platform):
    network = AdminNetwork()
    admin_enter(page, network, platform, mode="requirements")
    publication_draft(page)
    page.locator("#admin-review").click()
    expect(page.locator("#admin-confirmation")).to_contain_text("Literal <img")
    expect(page.locator("#admin-confirmation")).to_contain_text(
        "Synthetic recipient"
    )
    assert page.locator("#admin-confirmation img").count() == 0
    page.locator("#admin-submit").click()
    expect(page.locator("#admin-form")).to_be_empty()
    body = next(b for p, b in network.requests if p.endswith("/publish"))
    assert body["expected_version"] == 9
    assert body["effective_from"] == "2099-10-24T12:00:00+03:00"
    assert body["document"]["content_text"].endswith("Literal <img src=x>")
    assert body["field_definitions"] == requirements()["field_definitions"]
    assert body["enabled"] is True


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_disable_needs_no_invented_document(page, platform):
    network = AdminNetwork()
    admin_enter(page, network, platform, mode="requirements")
    publication_draft(page)
    page.locator("#admin-enabled").uncheck()
    page.locator("#admin-document-mode").select_option("none")
    page.locator("#admin-review").click()
    page.locator("#admin-submit").click()
    expect(page.locator("#admin-form")).to_be_empty()
    body = next(b for p, b in network.requests if p.endswith("/publish"))
    assert body["enabled"] is False
    assert body.get("document") is None
    assert body.get("field_definitions") is None


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_reuses_only_actual_immutable_document(page, platform):
    network = AdminNetwork()
    admin_enter(page, network, platform, mode="requirements")
    page.locator("#admin-list details summary").first.click()
    page.locator("#admin-list [data-admin-draft]").first.click()
    page.locator("#admin-effective-from").fill("2099-10-25T12:00:00Z")
    page.locator("#admin-review").click()
    expect(page.locator("#admin-confirmation")).to_contain_text(
        "SYNTHETIC TEST DOCUMENT"
    )
    page.locator("#admin-submit").click()
    expect(page.locator("#admin-form")).to_be_empty()
    body = next(b for p, b in network.requests if p.endswith("/publish"))
    assert body["document"] == {"document_id": DOC}


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "bad", ["naive", "schema", "source-label", "enabled-no-document"]
)
def test_admin_publication_rejects_invalid_source_contract(page, platform, bad):
    network = AdminNetwork()
    admin_enter(page, network, platform, mode="requirements")
    publication_draft(page)
    if bad == "naive":
        page.locator("#admin-effective-from").fill("2099-10-24T12:00:00")
    elif bad == "schema":
        page.locator("#admin-required-fields").fill(
            "recipient_name\nbank_account\nlegal_status\nlegal_status"
        )
    elif bad == "source-label":
        page.locator("#admin-source-locale").fill("uz")
    else:
        page.locator("#admin-document-mode").select_option("none")
    page.locator("#admin-review").click()
    expect(page.locator("#admin-submit")).to_have_count(0)
    assert not any(p.endswith("/publish") for p, _ in network.requests)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_unknown_publication_reads_history_without_replay(page, platform):
    network = AdminNetwork()
    network.lost.add("/payouts/admin/requirements/publish")
    admin_enter(page, network, platform, mode="requirements")
    publication_draft(page)
    page.locator("#admin-review").click()
    page.locator("#admin-submit").click()
    expect(page.locator("#admin-uncertain")).to_be_visible()
    expect(page.locator("#admin-reconciled")).to_be_visible()
    expect(page.locator("#admin-form")).to_be_empty()
    assert len([p for p, _ in network.requests if p.endswith("/publish")]) == 1
    assert (
        len(
            [
                p
                for p, _ in network.requests
                if p == "/payouts/read/admin/requirements"
            ]
        )
        >= 2
    )
    assert not any(
        p.endswith("/operations/status") for p, _ in network.requests
    )


def decision(page, action="review"):
    page.locator(f"#admin-action-{action}").click()
    page.locator("#admin-reason").fill("SYNTHETIC PRIVATE REASON")
    if action in ("review", "start"):
        page.locator("#admin-evidence-reference").fill(
            "SYNTHETIC PRIVATE EVIDENCE"
        )


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("action", ["review", "reject", "start", "escalate"])
def test_admin_decisions_follow_actions_not_state_guesses(
    page, platform, action
):
    network = AdminNetwork()
    selected(page, network, platform)
    decision(page, action)
    page.locator("#admin-review").click()
    page.locator("#admin-submit").click()
    expect(page.locator("#admin-form")).to_be_empty()
    body = next(b for p, b in network.requests if p == "/payouts/admin/command")
    assert body["expected_version"] == 8
    assert body["request_id"] == REQUEST
    assert body["action"] == action
    assert body["reason"] == "SYNTHETIC PRIVATE REASON"
    assert not any("bank" in p for p, _ in network.requests)
    expect(page.locator("#screen-payout-admin")).to_have_attribute(
        "aria-busy", "false"
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_review_and_start_require_actual_evidence(page, platform):
    network = AdminNetwork()
    selected(page, network, platform)
    decision(page)
    page.locator("#admin-evidence-reference").fill("")
    page.locator("#admin-review").click()
    expect(page.locator("#admin-submit")).to_have_count(0)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_prepare_is_not_bank_transfer(page, platform):
    network = AdminNetwork()
    selected(page, network, platform)
    decision(page, "start")
    expect(page.locator("#admin-form")).to_contain_text("outside UMC")
    page.locator("#admin-review").click()
    expect(page.locator("#admin-submit")).to_have_text(
        "Prepare manual transfer"
    )
    page.locator("#admin-submit").click()
    expect(page.locator("#admin-receipt")).to_contain_text(FENCE)
    expect(page.locator("#admin-detail")).to_contain_text(EXECUTION)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_blocked_reply_is_not_requested_success(page, platform):
    network = AdminNetwork()
    network.response_state = "blocked"
    selected(page, network, platform)
    decision(page)
    page.locator("#admin-review").click()
    page.locator("#admin-submit").click()
    expect(page.locator("#admin-receipt")).to_contain_text("Review required")


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_reveal_requires_explicit_reasoned_audit(page, platform):
    network = AdminNetwork()
    selected(page, network, platform)
    assert not any(p.endswith("/requisites") for p, _ in network.requests)
    page.locator("#admin-action-reveal_requisites").click()
    page.locator("#admin-reason").fill("SYNTHETIC AUDIT REASON")
    page.locator("#admin-review").click()
    page.locator("#admin-submit").click()
    expect(page.locator("#admin-reveal")).to_contain_text(
        "SYNTHETIC REVEAL PRIVATE"
    )
    expect(page.locator("#admin-form")).to_be_empty()
    body = next(b for p, b in network.requests if p.endswith("/requisites"))
    assert body["reason"] == "SYNTHETIC AUDIT REASON"
    page.locator("#admin-hide-reveal").click()
    expect(page.locator("#admin-reveal")).to_be_empty()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_background_reads_preserve_active_form(page, platform):
    network = AdminNetwork()
    selected(page, network, platform)
    decision(page)
    page.locator("#admin-history-events").click()
    page.locator("#admin-refresh").click()
    expect(page.locator("#admin-reason")).to_have_value(
        "SYNTHETIC PRIVATE REASON"
    )
    expect(page.locator("#admin-evidence-reference")).to_have_value(
        "SYNTHETIC PRIVATE EVIDENCE"
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_late_reveal_cannot_populate_new_selection(page, platform):
    network = AdminNetwork()
    path = f"/payouts/admin/{REQUEST}/requisites"
    network.hold.add(path)
    selected(page, network, platform)
    page.locator("#admin-action-reveal_requisites").click()
    page.locator("#admin-reason").fill("SYNTHETIC AUDIT")
    page.locator("#admin-review").click()
    page.locator("#admin-submit").click()
    page.locator("[data-admin-select]").nth(1).click()
    expect(page.locator("#admin-detail")).to_contain_text(OTHER)
    next(r for p, r, _ in network.pending if p == path).fulfill(
        json={"private": "SYNTHETIC LATE SECRET"}
    )
    expect(page.locator("#admin-reveal")).to_be_empty()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_old_completion_cannot_clear_new_form(page, platform):
    network = AdminNetwork()
    path = f"/payouts/admin/{REQUEST}/requisites"
    network.hold.add(path)
    selected(page, network, platform)
    page.locator("#admin-action-reveal_requisites").click()
    page.locator("#admin-reason").fill("SYNTHETIC OLD")
    page.locator("#admin-review").click()
    page.locator("#admin-submit").click()
    page.locator("#admin-back").click()
    decision(page, "reject")
    next(r for p, r, _ in network.pending if p == path).fulfill(
        json={"private": "SYNTHETIC OLD SECRET"}
    )
    expect(page.locator("#admin-reason")).to_have_value(
        "SYNTHETIC PRIVATE REASON"
    )
    expect(page.locator("#admin-reveal")).to_be_empty()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_unknown_decision_refreshes_before_any_new_decision(
    page, platform
):
    network = AdminNetwork()
    network.lost.add("/payouts/admin/command")
    selected(page, network, platform)
    decision(page, "start")
    page.locator("#admin-review").click()
    page.locator("#admin-submit").click()
    expect(page.locator("#admin-uncertain")).to_be_visible()
    expect(page.locator("#admin-reconciled")).to_be_visible()
    expect(page.locator("#admin-form")).to_be_empty()
    expect(page.locator("#admin-action-start")).to_be_disabled()
    assert (
        len([p for p, _ in network.requests if p == "/payouts/admin/command"])
        == 1
    )
    assert any("/history/intents" in p for p, _ in network.requests)


def observation(page, status="paid", amount="", currency=""):
    page.locator("[data-admin-observe]").first.click()
    page.locator("#admin-observed-status").select_option(status)
    page.locator("#admin-reason").fill("SYNTHETIC ACTUAL REASON")
    page.locator("#admin-evidence-reference").fill("SYNTHETIC ACTUAL EVIDENCE")
    page.locator("#admin-evidence-hash").fill(HASH)
    page.locator("#admin-observed-amount").fill(amount)
    page.locator("#admin-observed-currency").fill(currency)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_actual_observation_fields_start_blank(page, platform):
    network = AdminNetwork()
    selected(page, network, platform)
    page.locator("[data-admin-observe]").first.click()
    for key in (
        "observed-status",
        "observed-amount",
        "observed-currency",
        "settled-at",
        "bank-account",
        "bank-reference",
        "evidence-reference",
        "evidence-hash",
        "reason",
    ):
        expect(page.locator(f"#admin-{key}")).to_have_value("")
    expect(page.locator("#admin-form")).to_contain_text(
        "EXPECTED SYNTHETIC ORIGIN"
    )
    assert page.locator(".admin-recipient-key").count() == 0


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "amount",
    [
        "",
        "0",
        "-1",
        "9007199254740993",
        "9223372036854775807",
        "-9223372036854775807",
    ],
)
def test_admin_signed_observed_minor_range_and_null(page, platform, amount):
    network = AdminNetwork()
    selected(page, network, platform)
    observation(page, "unknown", amount, "USD")
    page.locator("#admin-review").click()
    page.locator("#admin-submit").click()
    expect(page.locator("#admin-form")).to_be_empty()
    body = next(b for p, b in network.requests if p == "/payouts/admin/result")
    assert body["amount_minor"] == (amount if amount else None)
    assert body["currency"] == "USD"
    assert body["expected_version"] == 8
    assert body["execution_id"] == EXECUTION and body["fence"] == FENCE
    assert body["recipient_details"] == {}
    assert body["bank_account"] == "" and body["settled_at"] is None


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "amount",
    [
        "-0",
        "+1",
        "01",
        "1e2",
        "1.0",
        " 1",
        "١",
        "9223372036854775808",
        "-9223372036854775808",
    ],
)
def test_admin_invalid_observed_amount_never_sends(page, platform, amount):
    network = AdminNetwork()
    selected(page, network, platform)
    observation(page, amount=amount)
    page.locator("#admin-review").click()
    expect(page.locator("#admin-submit")).to_have_count(0)
    assert not any(p == "/payouts/admin/result" for p, _ in network.requests)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_paused_reporting_uses_retained_scope_without_start(
    page, platform
):
    network = AdminNetwork()
    network.context["writes_paused"] = True
    network.details[REQUEST]["allowed_actions"] = ["record_observation"]
    network.details[REQUEST].update(
        state="unavailable", version=None, current_execution=None
    )
    selected(page, network, platform)
    expect(page.locator("#admin-action-start")).to_have_count(0)
    observation(page)
    page.locator("#admin-review").click()
    page.locator("#admin-submit").click()
    expect(page.locator("#admin-history-outcomes-page")).to_contain_text(
        "Not applied"
    )
    expect(page.locator("#admin-history-outcomes-page")).to_contain_text(
        "Recorded for review"
    )
    assert not any(p == "/payouts/admin/command" for p, _ in network.requests)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_missing_retained_version_requires_operator_recorded_version(
    page, platform
):
    network = AdminNetwork()
    network.details[REQUEST]["observation"]["retained_intents"]["entries"] = [
        intent(None, "retained_version_required")
    ]
    selected(page, network, platform)
    observation(page)
    expect(page.locator("#admin-expected-version")).to_have_value("")
    expect(page.locator("#admin-form")).to_contain_text("Operator-recorded")
    page.locator("#admin-review").click()
    expect(page.locator("#admin-submit")).to_have_count(0)
    page.locator("#admin-expected-version").fill("23")
    page.locator("#admin-review").click()
    page.locator("#admin-submit").click()
    expect(page.locator("#admin-form")).to_be_empty()
    assert (
        next(b for p, b in network.requests if p == "/payouts/admin/result")[
            "expected_version"
        ]
        == 23
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_history_intent_uses_actual_version_key(page, platform):
    network = AdminNetwork()
    network.histories["intents"] = page_of(
        [
            {k: v for k, v in intent().items() if k != "expected_version"}
            | {"version": 27}
        ]
    )
    selected(page, network, platform)
    page.locator("#admin-history-intents").click()
    page.locator("#admin-history-intents-page summary").click()
    page.locator("[data-admin-history-observe]").click()
    expect(page.locator("#admin-observation-scope")).to_contain_text("27")
    expect(page.locator("#admin-expected-version")).to_have_count(0)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_historical_recipient_fields_are_not_current_schema_or_proof(
    page, platform
):
    network = AdminNetwork()
    selected(page, network, platform)
    observation(page)
    page.locator("#admin-add-recipient").click()
    page.locator(".admin-recipient-key").fill("old_frozen_extra")
    page.locator(".admin-recipient-value").fill(
        "SYNTHETIC ACTUAL RECIPIENT EVIDENCE"
    )
    page.locator("#admin-review").click()
    page.locator("#admin-submit").click()
    expect(page.locator("#admin-form")).to_be_empty()
    body = next(b for p, b in network.requests if p == "/payouts/admin/result")
    assert body["recipient_details"] == {
        "old_frozen_extra": "SYNTHETIC ACTUAL RECIPIENT EVIDENCE"
    }


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_terminal_state_and_later_exception_are_both_visible(
    page, platform
):
    network = AdminNetwork()
    network.response_state = "paid"
    selected(page, network, platform)
    observation(page, amount="-1", currency="OTHER")
    page.locator("#admin-review").click()
    page.locator("#admin-submit").click()
    expect(page.locator("#admin-detail")).to_contain_text("Paid")
    expect(page.locator("#admin-history-outcomes-page")).to_contain_text(
        "Not applied"
    )
    expect(page.locator("#admin-history-outcomes-page")).to_contain_text("-1")
    expect(page.locator("#admin-history-outcomes-page")).to_contain_text(
        "OTHER"
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_unknown_result_refreshes_outcomes_without_replay(page, platform):
    network = AdminNetwork()
    network.lost.add("/payouts/admin/result")
    selected(page, network, platform)
    observation(page)
    page.locator("#admin-review").click()
    page.locator("#admin-submit").click()
    expect(page.locator("#admin-uncertain")).to_be_visible()
    expect(page.locator("#admin-reconciled")).to_be_visible()
    assert (
        len([p for p, _ in network.requests if p == "/payouts/admin/result"])
        == 1
    )
    assert any("/history/outcomes" in p for p, _ in network.requests)
    expect(page.locator("#admin-form")).to_be_empty()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_submit_completion_clears_captured_private_form(page, platform):
    network = AdminNetwork()
    selected(page, network, platform)
    observation(page)
    page.locator("#admin-add-recipient").click()
    page.locator(".admin-recipient-key").fill("SYNTHETIC_PRIVATE_KEY")
    page.locator(".admin-recipient-value").fill("SYNTHETIC_PRIVATE_VALUE")
    page.locator("#admin-review").click()
    page.evaluate(
        "window.__capturedAdminForm=document.getElementById('admin-private-form')"
    )
    page.locator("#admin-submit").click()
    expect(page.locator("#admin-form")).to_be_empty()
    assert page.evaluate("window.__capturedAdminForm.textContent") == ""


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_account_or_role_loss_clears_every_private_region(page, platform):
    network = AdminNetwork()
    selected(page, network, platform)
    decision(page)
    page.evaluate("window.__host.wa.initData='different-synthetic-account'")
    page.locator("#admin-review").click()
    expect(page.locator("#admin-form")).to_be_empty()
    expect(page.locator("#admin-detail")).to_be_empty()
    assert not any(p == "/payouts/admin/command" for p, _ in network.requests)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_role_loss_after_reveal_clears_plaintext(page, platform):
    network = AdminNetwork()
    selected(page, network, platform)
    page.locator("#admin-action-reveal_requisites").click()
    page.locator("#admin-reason").fill("SYNTHETIC AUDIT")
    page.locator("#admin-review").click()
    page.locator("#admin-submit").click()
    expect(page.locator("#admin-reveal")).to_contain_text(
        "SYNTHETIC REVEAL PRIVATE"
    )
    network.context["admin"] = False
    page.locator("#admin-refresh").click()
    expect(page.locator("#admin-reveal")).to_be_empty()
    expect(page.locator("#admin-detail")).to_be_empty()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_missing_secure_key_generation_keeps_reads_only(page, platform):
    network = AdminNetwork()
    selected(page, network, platform)
    page.evaluate(
        "() => { Object.defineProperty(window.crypto,'randomUUID',"
        "{value:undefined}); Object.defineProperty(window.crypto,"
        "'getRandomValues',{value:undefined}); }"
    )
    decision(page)
    page.locator("#admin-review").click()
    expect(page.locator("#admin-submit")).to_be_disabled()
    expect(page.locator("#admin-confirmation")).to_contain_text(
        "Secure operation keys are unavailable"
    )
    page.locator("#admin-history-events").click()
    expect(page.locator("#admin-history-events-page")).to_contain_text(
        "SYNTHETIC event"
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_native_main_is_current_visible_final_action(page, platform):
    network = AdminNetwork()
    selected(page, network, platform, native=True)
    observation(page, "unknown", "-1", "USD")
    page.locator("#admin-review").click()
    page.wait_for_function(
        "window.__host.wa.MainButton.params.text==='Record bank observation'"
    )
    page.evaluate(
        "window.__host.wa.MainButton.click(); "
        "window.__host.wa.MainButton.click();"
    )
    expect(page.locator("#admin-form")).to_be_empty()
    assert (
        len([p for p, _ in network.requests if p == "/payouts/admin/result"])
        == 1
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_native_back_clears_pending_form(page, platform):
    network = AdminNetwork()
    network.hold.add("/payouts/admin/command")
    selected(page, network, platform, native=True)
    decision(page, "start")
    page.locator("#admin-review").click()
    page.wait_for_function(
        "window.__host.wa.MainButton.params.text==='Prepare manual transfer'"
    )
    page.evaluate("window.__host.wa.MainButton.click()")
    page.wait_for_function(
        "document.getElementById('screen-payout-admin')"
        ".getAttribute('aria-busy')==='true'"
    )
    page.evaluate("window.__host.wa.BackButton.click()")
    expect(page.locator("#admin-form")).to_be_empty()
    expect(page.locator("#admin-uncertain")).to_be_visible()
    expect(page.locator("#admin-reconciled")).to_be_visible()
    for path, route, _ in network.pending:
        if path == "/payouts/admin/command":
            route.fulfill(json=admin_detail(state="executing"))
    expect(page.locator("#admin-form")).to_be_empty()
    assert not any(p == "/payouts/admin/result" for p, _ in network.requests)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_keyboard_focus_labels_live_regions(page, platform):
    network = AdminNetwork()
    selected(page, network, platform)
    observation(page)
    assert page.locator(
        "#admin-private-form input, #admin-private-form textarea, "
        "#admin-private-form select"
    ).evaluate_all(
        "nodes => nodes.every(n=>!!document.querySelector("
        "'label[for=\"'+n.id+'\"]') && "
        "n.getAttribute('aria-describedby')==='admin-error')"
    )
    expect(page.locator("#admin-live")).to_have_attribute("aria-live", "polite")
    page.locator("#admin-observed-amount").fill("+1")
    page.locator("#admin-review").click()
    expect(page.locator("#admin-error")).to_be_focused()


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("locale", ["ru", "en", "kk", "be", "uz", "unknown"])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_admin_320_light_dark_five_locales_and_ru_fallback(
    page, platform, locale, theme
):
    network = AdminNetwork(locale)
    network.details[REQUEST]["current_execution"]["bank_account"] = ""
    network.details[REQUEST]["observation"]["retained_intents"]["entries"][0][
        "bank_account"
    ] = ""
    page.set_viewport_size({"width": 320, "height": 800})
    errors = selected(page, network, platform)
    page.evaluate(
        "theme => { document.documentElement.dataset.theme=theme; }", theme
    )
    page.locator("[data-admin-observe]").first.click()
    titles = {
        "en": "Record bank observation",
        "ru": "Записать банковское наблюдение",
        "kk": "Банк бақылауын тіркеу",
        "be": "Запісаць банкаўскае назіранне",
        "uz": "Bank kuzatuvini qayd etish",
    }
    expect(page.locator("#admin-form h2")).to_have_text(
        titles.get(locale, titles["ru"])
    )
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screenshot(
        page, f"synthetic-admin-{platform}-{locale}-observation-320-{theme}"
    )
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_no_private_sink_or_reload_replay(page, platform):
    network = AdminNetwork()
    network.lost.add("/payouts/admin/result")
    errors = selected(page, network, platform)
    before = page.evaluate("JSON.stringify(localStorage)")
    observed = []
    page.on("console", lambda entry: observed.append(entry.text))
    observation(page, "unknown")
    page.locator("#admin-review").click()
    page.locator("#admin-submit").click()
    expect(page.locator("#admin-uncertain")).to_be_visible()
    expect(page.locator("#admin-reconciled")).to_be_visible()
    assert page.evaluate("JSON.stringify(localStorage)") == before
    assert page.evaluate("sessionStorage.length") == 0
    assert "SYNTHETIC ACTUAL" not in page.url
    assert not any("SYNTHETIC ACTUAL" in entry for entry in observed)
    page.reload()
    expect(page.locator("#admin-private-form")).to_have_count(0)
    expect(page.locator("#screen-payout-admin")).to_be_empty()
    assert (
        len([p for p, _ in network.requests if p == "/payouts/admin/result"])
        == 1
    )
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_observed_formatter_preserves_null_and_non_rub_currency(
    page, platform
):
    network = AdminNetwork()
    network.histories["outcomes"] = page_of(
        [
            {
                "outcome_id": OUTCOME,
                "amount_minor": None,
                "currency": None,
                "applied": False,
            },
            {
                "outcome_id": OTHER,
                "amount_minor": "-9223372036854775807",
                "currency": "OTHER",
                "applied": False,
            },
        ]
    )
    selected(page, network, platform)
    page.locator("#admin-history-outcomes").click()
    expect(page.locator("#admin-history-outcomes-page")).to_contain_text(
        "Not recorded"
    )
    expect(page.locator("#admin-history-outcomes-page")).to_contain_text(
        "-9223372036854775807"
    )
    expect(page.locator("#admin-history-outcomes-page")).to_contain_text(
        "OTHER"
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_stale_form_cannot_silently_rebase_version(page, platform):
    network = AdminNetwork()
    selected(page, network, platform)
    decision(page, "start")
    page.locator("#admin-review").click()
    network.details[REQUEST]["version"] = 12
    page.locator("#admin-refresh").click()
    expect(page.locator("#admin-detail-version")).to_have_text(
        "Record version: 12"
    )
    page.locator("#admin-submit").click()
    expect(page.locator("#admin-error")).to_contain_text("Data changed")
    assert not any(p == "/payouts/admin/command" for p, _ in network.requests)


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("status", ["failed", "unknown", "paid"])
def test_admin_actual_status_does_not_infer_application(page, platform, status):
    network = AdminNetwork()
    selected(page, network, platform)
    observation(page, status)
    page.locator("#admin-review").click()
    page.locator("#admin-submit").click()
    expect(page.locator("#admin-history-outcomes-page")).to_contain_text(
        "Not applied"
    )
    assert (
        next(b for p, b in network.requests if p == "/payouts/admin/result")[
            "status"
        ]
        == status
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_late_history_cannot_overwrite_later_selection_form(
    page, platform
):
    network = AdminNetwork()
    path = f"/payouts/read/admin/{REQUEST}/history/events"
    network.hold.add(path)
    selected(page, network, platform)
    page.locator("#admin-history-events").click()
    page.locator("[data-admin-select]").nth(1).click()
    expect(page.locator("#admin-detail")).to_contain_text(OTHER)
    decision(page)
    next(r for p, r, _ in network.pending if p == path).fulfill(
        json=page_of([{"reason": "SYNTHETIC STALE HISTORY"}])
    )
    expect(page.locator("#admin-reason")).to_have_value(
        "SYNTHETIC PRIVATE REASON"
    )
    expect(page.locator("#admin-history")).not_to_contain_text(
        "SYNTHETIC STALE HISTORY"
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_navigation_is_independent_of_owner_pending_recovery(
    page, platform
):
    network = AdminNetwork()
    network.reserve_lost = True
    enter(page, network, platform)
    owner_review(page)
    page.locator("#payout-reserve").click()
    expect(page.locator("#payout-pending")).to_be_visible()
    page.locator("#payout-admin-queue").click()
    expect(page.locator("#admin-list")).to_contain_text(REQUEST)
    page.locator("#admin-back").click()
    expect(page.locator("#payout-pending")).to_be_visible()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_form_opens_at_heading_for_keyboard_navigation(page, platform):
    network = AdminNetwork()
    selected(page, network, platform)
    page.locator("#admin-action-reject").click()
    expect(page.locator("#admin-form h2")).to_be_focused()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_action_denials_are_localized_and_safe(page, platform):
    network = AdminNetwork()
    network.details[REQUEST]["allowed_actions"] = ["record_observation"]
    network.details[REQUEST]["action_blockers"] = {
        "ordinary": ["financial_payouts_disabled"],
        "reveal_requisites": ["payout_encryption_configuration_required"],
        "start": ["SYNTHETIC PRIVATE EXCEPTION"],
    }
    selected(page, network, platform)
    expect(page.locator("#admin-detail")).to_contain_text("paused")
    expect(page.locator("#admin-detail")).to_contain_text("Encryption")
    expect(page.locator("#admin-detail")).not_to_contain_text(
        "SYNTHETIC PRIVATE EXCEPTION"
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_conflict_refreshes_without_replay(page, platform):
    network = AdminNetwork()
    network.errors["/payouts/admin/command"] = (409, "payout_version_conflict")
    selected(page, network, platform)
    decision(page)
    page.locator("#admin-review").click()
    page.locator("#admin-submit").click()
    expect(page.locator("#admin-form")).to_be_empty()
    expect(page.locator("#admin-error")).to_contain_text("Data changed")
    expect(page.locator("#admin-reconciled")).to_be_visible()
    assert (
        len([p for p, _ in network.requests if p == "/payouts/admin/command"])
        == 1
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("view", ["queue", "publication", "cleared", "review"])
def test_admin_synthetic_blank_secret_visuals(page, platform, view):
    network = AdminNetwork()
    page.set_viewport_size({"width": 320, "height": 800})
    network.details[REQUEST]["amount_minor"] = "9223372036854775807"
    network.details[REQUEST]["current_execution"]["bank_account"] = ""
    network.details[REQUEST]["observation"]["retained_intents"]["entries"][0][
        "bank_account"
    ] = ""
    if view == "publication":
        errors = admin_enter(page, network, platform, mode="requirements")
        expect(page.locator("#admin-publication-new")).to_be_enabled()
    elif view == "queue":
        errors = admin_enter(page, network, platform)
        expect(page.locator("#admin-list")).to_contain_text(REQUEST)
    elif view == "cleared":
        errors = selected(page, network, platform)
        page.locator("#admin-action-reveal_requisites").click()
        page.locator("#admin-reason").fill("SYNTHETIC AUDIT")
        page.locator("#admin-review").click()
        page.locator("#admin-submit").click()
        expect(page.locator("#admin-reveal")).to_contain_text(
            "SYNTHETIC REVEAL PRIVATE"
        )
        page.locator("#admin-hide-reveal").click()
    else:
        network.context["writes_paused"] = True
        errors = selected(page, network, platform)
        observation(page)
        page.locator("#admin-review").click()
        page.locator("#admin-submit").click()
        expect(page.locator("#admin-reconciled")).to_be_visible()
        # Explicitly blank the synthetic protected evidence in the next
        # synthetic server response before capturing application status.
        network.histories["outcomes"]["entries"][0]["evidence_reference"] = ""
        page.locator("#admin-history-outcomes").click()
        page.locator("#admin-history-outcomes-page summary").click()
        expect(page.locator("#admin-history-outcomes-page")).to_contain_text(
            "Not applied"
        )
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert (
        "SYNTHETIC REVEAL PRIVATE"
        not in page.locator("#screen-payout-admin").inner_text()
    )
    screenshot(page, f"synthetic-admin-{platform}-{view}-320-light")
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "locale,enabled",
    [
        ("ru", "Включено"),
        ("en", "Enabled"),
        ("kk", "Қосылған"),
        ("be", "Уключана"),
        ("uz", "Yoqilgan"),
    ],
)
def test_admin_publication_flag_is_localized(page, platform, locale, enabled):
    network = AdminNetwork(locale)
    admin_enter(page, network, platform, mode="requirements")
    expect(page.locator("#admin-effective")).to_contain_text(enabled)
    expect(page.locator("#admin-effective")).not_to_contain_text("true")


def release_admin_response(page, route, path, body, status=200):
    """Await the response body and two controller/native animation frames."""
    with page.expect_response(
        lambda response: urlparse(response.url).path == "/miniapp/api" + path
    ) as response_info:
        route.fulfill(status=status, json=body)
    response = response_info.value
    assert response.status == status
    response.body()
    page.evaluate(
        "() => new Promise(resolve => requestAnimationFrame("
        "() => requestAnimationFrame(resolve)))"
    )


def owner_projection(request_id=REQUEST):
    """Actual shared-detail owner shape, with no protected admin additions."""
    return {
        key: value
        for key, value in (detail() | {"request_id": request_id}).items()
        if key not in ("current_execution", "allowed_actions")
    } | {"allowed_actions": []}


def select_other_and_review_reject(page, reason="SYNTHETIC CURRENT REASON"):
    page.locator("[data-admin-select]").nth(1).click()
    expect(page.locator("#admin-detail")).to_contain_text(OTHER)
    decision(page, "reject")
    page.locator("#admin-reason").fill(reason)
    page.locator("#admin-review").click()
    expect(page.locator("#admin-submit")).to_be_attached()
    page.wait_for_function("window.__host.wa.MainButton.visible")
    page.evaluate(
        "window.__authLossCapturedForm="
        "document.getElementById('admin-private-form')"
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "source,status",
    [("history", 403), ("reveal", 403), ("detail", 200), ("history", 401)],
)
def test_same_context_auth_loss_revokes_stale_target_globally(
    page, platform, source, status
):
    network = AdminNetwork()
    path = {
        "history": f"/payouts/read/admin/{REQUEST}/history/events",
        "reveal": f"/payouts/admin/{REQUEST}/requisites",
        "detail": f"/payouts/read/{REQUEST}/detail",
    }[source]
    network.hold.add(path)
    if source == "detail":
        admin_enter(page, network, platform, native=True)
        page.locator("[data-admin-select]").first.click()
    else:
        selected(page, network, platform, native=True)
        if source == "history":
            page.locator("#admin-history-events").click()
        else:
            page.locator("#admin-action-reveal_requisites").click()
            page.locator("#admin-reason").fill("SYNTHETIC OLD REVEAL REASON")
            page.locator("#admin-review").click()
            page.evaluate("window.__host.wa.MainButton.click()")
            page.wait_for_function(
                "document.getElementById('screen-payout-admin')"
                ".getAttribute('aria-busy')==='true'"
            )
            page.evaluate("window.__host.wa.BackButton.click()")
            expect(page.locator("#admin-reconciled")).to_be_visible()
    select_other_and_review_reject(page)
    held = next(route for p, route, _ in network.pending if p == path)
    body = (
        owner_projection()
        if source == "detail"
        else {
            "detail": "payout_read_session_invalid"
            if status == 401
            else "active_admin_required"
            if source == "reveal"
            else "payout_read_forbidden"
        }
    )
    release_admin_response(page, held, path, body, status)
    for identifier in (
        "context",
        "list",
        "detail",
        "history",
        "form",
        "reveal",
        "receipt",
    ):
        expect(page.locator(f"#admin-{identifier}")).to_be_empty()
    expect(page.locator("#admin-error")).to_contain_text(
        "session" if status == 401 else "administrator"
    )
    assert page.evaluate("window.__authLossCapturedForm.textContent") == ""
    assert not page.evaluate("window.__host.wa.MainButton.visible")
    assert page.locator("#screen-payout-admin [data-umc-primary]").count() == 0
    assert not any(p == "/payouts/admin/command" for p, _ in network.requests)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_disposed_context_denial_preserves_reopened_current_form(
    page, platform
):
    network = AdminNetwork()
    path = f"/payouts/read/admin/{REQUEST}/history/events"
    network.hold.add(path)
    selected(page, network, platform, native=True)
    page.locator("#admin-history-events").click()
    held = next(route for p, route, _ in network.pending if p == path)
    page.evaluate("window.__host.wa.BackButton.click()")
    expect(page.locator("#payout-balance")).to_be_visible()
    page.locator("#payout-admin-queue").click()
    select_other_and_review_reject(page, "SYNTHETIC REOPENED REASON")
    release_admin_response(
        page, held, path, {"detail": "payout_read_forbidden"}, 403
    )
    expect(page.locator("#admin-detail")).to_contain_text(OTHER)
    expect(page.locator("#admin-reason")).to_have_value(
        "SYNTHETIC REOPENED REASON"
    )
    expect(page.locator("#admin-error")).to_be_empty()
    assert page.evaluate("window.__host.wa.MainButton.visible")


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_stale_resource_404_does_not_revoke_current_form(page, platform):
    network = AdminNetwork()
    path = f"/payouts/read/admin/{REQUEST}/history/events"
    network.hold.add(path)
    selected(page, network, platform, native=True)
    page.locator("#admin-history-events").click()
    select_other_and_review_reject(page)
    held = next(route for p, route, _ in network.pending if p == path)
    release_admin_response(
        page, held, path, {"detail": "payout_read_not_found"}, 404
    )
    expect(page.locator("#admin-detail")).to_contain_text(OTHER)
    expect(page.locator("#admin-reason")).to_have_value(
        "SYNTHETIC CURRENT REASON"
    )
    expect(page.locator("#admin-error")).to_be_empty()
    assert page.evaluate("window.__host.wa.MainButton.visible")


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_empty_admin_allowed_actions_is_still_protected_detail(page, platform):
    network = AdminNetwork()
    network.details[REQUEST]["allowed_actions"] = []
    selected(page, network, platform)
    expect(page.locator("#admin-detail")).to_contain_text(REQUEST)
    expect(page.locator("#admin-error")).to_be_empty()
    page.locator("#admin-history-events").click()
    expect(page.locator("#admin-history-events-page")).to_contain_text(
        "SYNTHETIC event"
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_command_receipt_owner_shape_is_not_detail_authority_loss(
    page, platform
):
    network = AdminNetwork()
    path = "/payouts/admin/command"
    network.hold.add(path)
    selected(page, network, platform)
    decision(page, "review")
    page.locator("#admin-review").click()
    page.locator("#admin-submit").click()
    held = next(route for p, route, _ in network.pending if p == path)
    receipt = owner_projection() | {"version": 9, "state": "approved"}
    receipt.pop("allowed_actions")
    release_admin_response(page, held, path, receipt)
    expect(page.locator("#admin-receipt")).to_contain_text(
        "Original operation reply"
    )
    expect(page.locator("#admin-list")).to_contain_text(REQUEST)
    expect(page.locator("#admin-error")).to_be_empty()
