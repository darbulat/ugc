"""Actual collaboration UI, signed envelope and server capability boundary."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import UUID

import pytest
from playwright.sync_api import Route, expect

from tests.e2e.miniapp_helpers import generate_init_data
from tests.e2e.test_miniapp_design_system import (
    MiniAppNetwork,
    open_app,
    screenshot,
)
from ugc_bot.application.collaboration_ports import (
    CollaborationRecord,
    record_payload,
)
from ugc_bot.domain.collaboration import Collaboration

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
ASSIGNMENT = UUID("10000000-0000-4000-8000-000000000001")
CLIENT = UUID("10000000-0000-4000-8000-000000000002")
CREATOR = UUID("10000000-0000-4000-8000-000000000003")
MANAGER = UUID("10000000-0000-4000-8000-000000000004")
SIGNED_DATA = generate_init_data("test-token", 101, "synthetic_collaboration")
START = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


class CollaborationNetwork(MiniAppNetwork):
    def __init__(
        self,
        locale="ru",
        *,
        state="success_claimed",
        actor=CLIENT,
        actions=None,
    ):
        super().__init__(
            locale if locale in ("ru", "en", "kk") else "ru", registered=True
        )
        self.locale = locale
        work = Collaboration(
            assignment_id=ASSIGNMENT,
            client_id=CLIENT,
            creator_id=CREATOR,
            manager_id=MANAGER,
            due_at=START + timedelta(days=2),
            agreed_at=START,
        )
        if state != "assigned":
            work = work.start(actor_id=MANAGER, at=START)
        if state in (
            "success_claimed",
            "success_final",
            "disputed",
            "available",
        ):
            work = work.claim_success(
                actor_id=CREATOR,
                evidence="https://example.test/actual-synthetic-proof",
                at=START,
            )
        if state in ("success_final", "available"):
            work = work.agree(actor_id=CLIENT, at=START + timedelta(hours=1))
        if state == "unconfirmed_expired":
            work = work.advance(at=START + timedelta(days=17))
        if state == "available":
            work = work.advance(at=START + timedelta(days=15))
        if state == "disputed":
            work = work.dispute(
                actor_id=CLIENT,
                reason="Actual synthetic objection",
                at=START + timedelta(hours=71),
            )
        self.record = CollaborationRecord(
            work,
            UUID(int=20),
            UUID(int=21),
            "synthetic-approved-policy",
            "actual-synthetic-agreed-terms",
            3,
            START,
        )
        self.actor = actor
        self.actions = actions if actions is not None else ["agree", "dispute"]
        self.is_current = True
        self.status_code = 200
        self.command_code = 200
        self.abort_command = False
        self.replayed_command = False
        self.commands = []
        self.pending = []
        self.hold_command = False
        self.now = START + timedelta(hours=71)

    def response(self):
        work = self.record.collaboration
        return {
            "record": record_payload(self.record),
            "first_claim_deadline": work.first_claim_deadline.isoformat(),
            "objection_deadline": work.objection_deadline.isoformat()
            if work.objection_deadline
            else None,
            "available_at": work.available_at.isoformat()
            if work.available_at
            else None,
            "actor_id": str(self.actor),
            "allowed_actions": self.actions,
            "is_current": self.is_current,
        }

    def route(self, route: Route):
        path = urlparse(route.request.url).path
        if path == "/miniapp/api/me":
            self.requests.append(("/me", route.request.post_data_json))
            route.fulfill(
                json={
                    "locale": self.locale,
                    "country": "ru",
                    "currency_symbol": self.symbol,
                    "has_advertiser_profile": True,
                    "has_blogger_profile": False,
                    "blogger_profile": None,
                    "is_manager": False,
                }
            )
            return
        if not path.startswith(f"/miniapp/api/collaborations/{ASSIGNMENT}/"):
            super().route(route)
            return
        body = route.request.post_data_json
        self.requests.append((path.removeprefix("/miniapp/api"), body))
        if path.endswith("/status"):
            route.fulfill(
                status=self.status_code,
                json=self.response()
                if self.status_code == 200
                else {"detail": "Synthetic status unavailable"},
            )
            return
        self.commands.append(body)
        if self.abort_command:
            route.abort()
            return
        if self.hold_command:
            self.pending.append(route)
            return
        if self.command_code != 200:
            if self.command_code == 409:
                self.record = replace(
                    self.record, version=self.record.version + 1
                )
                self.actions = []
            route.fulfill(
                status=self.command_code,
                json={"detail": "Synthetic command conflict"},
            )
            return
        self.apply_command(route, body)

    def apply_command(self, route, body):
        work = self.record.collaboration
        action = body["action"]
        if action == "claim":
            work = work.claim_success(
                actor_id=self.actor,
                evidence=body["evidence"],
                at=START + timedelta(hours=1),
            )
        elif action == "dispute":
            work = work.dispute(
                actor_id=self.actor, reason=body["reason"], at=self.now
            )
        elif action == "agree":
            work = work.agree(actor_id=self.actor, at=self.now)
        elif action == "start":
            work = work.start(actor_id=self.actor, at=self.now)
        elif action == "extend_due":
            work = work.extend_due(
                actor_id=self.actor,
                due_at=datetime.fromisoformat(
                    body["due_at"].replace("Z", "+00:00")
                ),
                expected_due_version=body["expected_due_version"],
                at=self.now,
            )
        self.record = replace(
            self.record, collaboration=work, version=self.record.version + 1
        )
        self.actions = []
        data = self.response()
        if self.replayed_command:
            data["is_current"] = False
        route.fulfill(json=data)


def open_work(page, network, platform="telegram", *, native=False, query=None):
    return open_app(
        page,
        network,
        platform,
        native=native,
        init_data=SIGNED_DATA,
        query=query if query is not None else f"?assignment={ASSIGNMENT}",
    )


def command_payload(network, platform, action):
    assert len(network.commands) == 1
    body = network.commands[0]
    assert body["init_data"] == SIGNED_DATA and body["platform"] == platform
    assert body["action"] == action and body["expected_version"] == 3
    assert (
        isinstance(body["operation_key"], str)
        and 0 < len(body["operation_key"]) <= 200
    )
    assert not {
        "actor_id",
        "system_actor",
        "accepted",
        "channel",
        "external_reference",
    }.intersection(body)
    return body


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("locale", ["ru", "en", "kk", "be", "uz"])
def test_notice_deep_link_displays_real_status_proof_and_deadlines(
    page, platform, locale
):
    network = CollaborationNetwork(locale)
    page.set_viewport_size({"width": 320, "height": 800})
    errors = open_work(page, network, platform)
    expect(page.locator("#screen-collaboration")).to_be_visible()
    expect(page.locator("html")).to_have_attribute("lang", locale)
    expect(page.locator("#collaboration-status")).to_have_attribute(
        "data-state", "success_claimed"
    )
    expect(page.locator("#collaboration-evidence-view a")).to_have_attribute(
        "href", "https://example.test/actual-synthetic-proof"
    )
    expect(
        page.locator('[data-collaboration-time="objection_deadline"]')
    ).to_have_attribute("datetime", (START + timedelta(hours=72)).isoformat())
    expect(page.locator('[data-collaboration-action="agree"]')).to_be_visible()
    expect(
        page.locator('[data-collaboration-action="dispute"]')
    ).to_be_visible()
    expect(page.locator('[data-collaboration-action="claim"]')).to_have_count(0)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if locale in ("kk", "be", "uz"):
        assert (
            "October" not in page.locator("#collaboration-dates").inner_text()
        )
    assert not errors
    screenshot(page, f"collaboration-{platform}-{locale}-claimed-light")


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_claim_requires_real_proof_and_uses_current_server_version(
    page, platform
):
    network = CollaborationNetwork(
        state="in_progress", actor=CREATOR, actions=["claim"]
    )
    errors = open_work(page, network, platform)
    page.locator('[data-collaboration-action="claim"]').click()
    expect(page.locator("#form-collaboration-command")).to_be_visible()
    page.locator("#btn-collaboration-submit").click()
    assert not network.commands
    page.locator("#collaboration-evidence").fill("https://example.test/my-post")
    page.locator("#btn-collaboration-submit").click()
    assert not errors
    expect(page.locator("#collaboration-status")).to_have_attribute(
        "data-state", "success_claimed"
    )
    body = command_payload(network, platform, "claim")
    assert body["evidence"] == "https://example.test/my-post"
    assert set(body) == {
        "init_data",
        "platform",
        "action",
        "operation_key",
        "expected_version",
        "evidence",
    }


@pytest.mark.parametrize("action", ["agree", "dispute"])
def test_opposite_party_explicit_action_and_reason_at_71_hours(page, action):
    network = CollaborationNetwork()
    open_work(page, network)
    page.locator(f'[data-collaboration-action="{action}"]').click()
    assert not network.commands
    if action == "dispute":
        page.locator("#btn-collaboration-submit").click()
        assert not network.commands
        page.locator("#collaboration-reason").fill(
            "The published content does not match the agreed brief"
        )
    page.locator("#btn-collaboration-submit").click()
    expect(page.locator("#collaboration-status")).to_have_attribute(
        "data-state", "disputed" if action == "dispute" else "success_final"
    )
    body = command_payload(network, "telegram", action)
    if action == "dispute":
        assert (
            body["reason"]
            == "The published content does not match the agreed brief"
        )
    else:
        expect(
            page.locator('[data-collaboration-time="available_at"]')
        ).to_have_attribute(
            "datetime", (network.now + timedelta(days=14)).isoformat()
        )


@pytest.mark.parametrize("status", [403, 404, 503])
def test_status_failure_has_no_invented_record_or_action(page, status):
    network = CollaborationNetwork()
    network.status_code = status
    open_work(page, network)
    expect(page.locator("#screen-collaboration")).to_be_visible()
    expect(page.locator("#collaboration-error")).not_to_be_empty()
    expect(page.locator("[data-collaboration-action]")).to_have_count(0)
    expect(page.locator("#collaboration-details")).to_be_hidden()
    assert not network.commands


def test_409_refreshes_status_without_replaying_command(page):
    network = CollaborationNetwork()
    network.command_code = 409
    open_work(page, network)
    page.locator('[data-collaboration-action="agree"]').click()
    page.locator("#btn-collaboration-submit").click()
    expect(page.locator("#collaboration-feedback")).not_to_be_empty()
    expect(page.locator("[data-collaboration-action]")).to_have_count(0)
    assert len(network.commands) == 1
    assert (
        len([path for path, _ in network.requests if path.endswith("/status")])
        == 2
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_native_submit_follows_real_pending_command_without_duplicate(
    page, platform
):
    network = CollaborationNetwork(
        state="in_progress", actor=CREATOR, actions=["claim"]
    )
    network.hold_command = True
    open_work(page, network, platform, native=True)
    page.locator('[data-collaboration-action="claim"]').click()
    page.locator("#collaboration-evidence").fill("Actual supplied proof")
    page.wait_for_function("window.__host.wa.MainButton.visible")
    page.evaluate("window.__host.wa.MainButton.click()")
    page.wait_for_function(
        "window.__host.wa.MainButton.params.is_active === false"
    )
    page.evaluate("window.__host.wa.MainButton.click()")
    assert len(network.commands) == 1
    expect(page.locator("#form-collaboration-command")).to_have_attribute(
        "aria-busy", "true"
    )
    network.actions = []
    network.pending[0].fulfill(json=network.response())
    expect(page.locator("#form-collaboration-command")).to_be_hidden()


def test_historical_assignment_and_stale_me_cannot_invent_permissions(page):
    network = CollaborationNetwork(actor=CREATOR, actions=[])
    network.is_current = False
    errors = open_work(page, network)
    expect(page.locator("#screen-collaboration")).to_be_visible()
    expect(page.locator("[data-collaboration-action]")).to_have_count(0)
    expect(page.locator("#collaboration-readonly")).to_be_visible()
    assert not errors and not network.commands


def test_invalid_or_ambiguous_assignment_link_never_requests_private_status(
    page,
):
    network = CollaborationNetwork()
    open_work(
        page, network, query=f"?assignment={ASSIGNMENT}&assignment={CREATOR}"
    )
    expect(page.locator("#screen-collaboration")).to_be_visible()
    expect(page.locator("#collaboration-error")).not_to_be_empty()
    assert not any(
        path.startswith("/collaborations/") for path, _ in network.requests
    )


def test_safe_evidence_failed_notice_and_dark_readonly_state(page):
    network = CollaborationNetwork(actions=[])
    network.record = replace(
        network.record,
        collaboration=replace(
            network.record.collaboration,
            evidence='<img src=x onerror="window.syntheticXss=1">',
            notice_failed_at=START,
        ),
    )
    errors = open_work(page, network, query=f"?assignment_id={ASSIGNMENT}")
    expect(page.locator("#screen-collaboration")).to_be_visible()
    expect(page.locator("#collaboration-evidence-view")).to_contain_text("<img")
    expect(page.locator("#collaboration-evidence-view img")).to_have_count(0)
    expect(page.locator("#collaboration-notice-state")).not_to_be_empty()
    page.evaluate(
        "window.__host.wa.colorScheme='dark'; "
        "window.__host.events.themeChanged()"
    )
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    assert not page.evaluate("window.syntheticXss || false")
    assert not errors
    screenshot(page, "collaboration-telegram-failed-notice-dark")


@pytest.mark.parametrize("action", ["start", "request_confirmation"])
def test_manager_commands_use_only_current_server_capability(page, action):
    network = CollaborationNetwork(
        "en",
        state="assigned" if action == "start" else "in_progress",
        actor=MANAGER,
        actions=[action],
    )
    errors = open_work(page, network, "max")
    expect(page.locator("[data-collaboration-action]")).to_have_count(1)
    page.locator(f'[data-collaboration-action="{action}"]').click()
    assert not network.commands
    screenshot(page, f"collaboration-max-manager-{action}-form")
    page.locator("#btn-collaboration-submit").click()
    expect(page.locator("#form-collaboration-command")).to_be_hidden()
    body = command_payload(network, "max", action)
    assert set(body) == {
        "init_data",
        "platform",
        "action",
        "operation_key",
        "expected_version",
    }
    assert not errors


def test_client_extension_uses_due_version_terms_reason_without_resetting_72h(
    page,
):
    page.set_viewport_size({"width": 320, "height": 800})
    network = CollaborationNetwork("kk", actions=["extend_due"])
    errors = open_work(page, network)
    original_deadline = (
        network.record.collaboration.objection_deadline.isoformat()
    )
    page.locator('[data-collaboration-action="extend_due"]').click()
    page.locator("#btn-collaboration-submit").click()
    assert not network.commands
    page.locator("#collaboration-due-at").fill("2026-10-28T12:00")
    page.locator("#collaboration-terms").fill("Actual new client-agreed terms")
    page.locator("#collaboration-reason").fill(
        "Actual client consent to the schedule change"
    )
    expect(page.locator("#collaboration-error")).to_be_empty()
    screenshot(page, "collaboration-telegram-kk-extension-form")
    page.locator("#btn-collaboration-submit").click()
    expect(page.locator("#form-collaboration-command")).to_be_hidden()
    body = command_payload(network, "telegram", "extend_due")
    assert body["expected_due_version"] == 1
    assert body["terms_reference"] == "Actual new client-agreed terms"
    assert body["reason"] == "Actual client consent to the schedule change"
    assert body["due_at"] == page.evaluate(
        "new Date('2026-10-28T12:00').toISOString()"
    )
    expect(
        page.locator('[data-collaboration-time="objection_deadline"]')
    ).to_have_attribute("datetime", original_deadline)
    assert not errors


@pytest.mark.parametrize(
    "state", ["unconfirmed_expired", "success_final", "available", "disputed"]
)
def test_terminal_and_hold_states_remain_actual_readonly_records(page, state):
    network = CollaborationNetwork("en", state=state, actions=[])
    errors = open_work(page, network)
    expect(page.locator("#collaboration-status")).to_have_attribute(
        "data-state", state
    )
    expect(page.locator("#collaboration-readonly")).to_be_visible()
    expect(page.locator("[data-collaboration-action]")).to_have_count(0)
    screenshot(page, f"collaboration-telegram-{state}-readonly")
    assert not errors


def test_network_uncertainty_refreshes_without_automatic_resubmission(page):
    network = CollaborationNetwork()
    network.abort_command = True
    errors = open_work(page, network)
    page.locator('[data-collaboration-action="agree"]').click()
    page.locator("#btn-collaboration-submit").click()
    expect(page.locator("#collaboration-feedback")).not_to_be_empty()
    expect(page.locator("#form-collaboration-command")).to_be_hidden()
    assert len(network.commands) == 1
    assert (
        len([path for path, _ in network.requests if path.endswith("/status")])
        == 2
    )
    assert not errors


def test_historical_idempotent_command_response_refreshes_current_status(page):
    network = CollaborationNetwork()
    network.replayed_command = True
    open_work(page, network)
    page.locator('[data-collaboration-action="agree"]').click()
    page.locator("#btn-collaboration-submit").click()
    expect(page.locator("#collaboration-feedback")).not_to_be_empty()
    expect(page.locator("#collaboration-status")).to_have_attribute(
        "data-state", "success_final"
    )
    assert len(network.commands) == 1
    assert (
        len([path for path, _ in network.requests if path.endswith("/status")])
        == 2
    )


@pytest.mark.parametrize("status", [403, 503])
def test_command_denial_removes_actions_without_fake_success(page, status):
    network = CollaborationNetwork()
    network.command_code = status
    open_work(page, network)
    page.locator('[data-collaboration-action="agree"]').click()
    page.locator("#btn-collaboration-submit").click()
    expect(page.locator("#collaboration-error")).not_to_be_empty()
    expect(page.locator("[data-collaboration-action]")).to_have_count(0)
    expect(page.locator("#form-collaboration-command")).to_be_hidden()
    expect(page.locator("#collaboration-status")).to_have_attribute(
        "data-state", "success_claimed"
    )
    assert len(network.commands) == 1


def test_native_back_cancels_selected_decision_then_returns_to_dashboard(page):
    network = CollaborationNetwork("en")
    errors = open_work(page, network, native=True)
    expect(page.locator("#screen-collaboration")).to_be_visible()
    # No native default agreement is chosen when two server actions exist.
    page.wait_for_function("window.__host.wa.MainButton.visible === false")
    choice = page.locator('[data-collaboration-action="dispute"]')
    choice.focus()
    choice.press("Enter")
    expect(page.locator("#form-collaboration-command")).to_be_visible()
    page.evaluate("window.__host.wa.BackButton.click()")
    expect(page.locator("#form-collaboration-command")).to_be_hidden()
    expect(page.locator("#screen-collaboration")).to_be_visible()
    page.evaluate("window.__host.wa.BackButton.click()")
    expect(page.locator("#screen-advertiser-dashboard")).to_be_visible()
    assert "assignment=" not in page.url
    assert not network.commands and not errors
