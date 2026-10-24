"""Actual campaign editor assets; only host and signed network are synthetic."""

from copy import deepcopy
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_campaign_settings import CampaignNetwork
from tests.e2e.test_miniapp_design_system import open_app, screenshot

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
CAMPAIGN = "20000000-0000-4000-8000-000000000001"
DIGEST = "d" * 64
AT = "2026-10-24T12:00:00Z"


def draft(title="SYNTHETIC saved task", version=1):
    return {
        "campaign_id": CAMPAIGN,
        "version": version,
        "revision_digest": DIGEST,
        "state": "draft",
        "content": {"title": title, "text": "SYNTHETIC actual task body"},
        "segment": {},
        "policy_version": 1,
        "terms_hash": "a" * 64,
        "recorded_at": AT,
        "submission_state": "not_implemented",
    }


class WorkbenchNetwork(CampaignNetwork):
    def __init__(self, locale="ru", admin=False):
        super().__init__(admin=admin, locale=locale)
        self.settings["publisher"]["active"] = True
        self.settings["policy"]["limits"].update(
            title_max_chars=100, text_max_chars=2000, link_max_chars=500
        )
        self.settings["capabilities"] = {
            "read_own_drafts": True,
            "read_own_operations": True,
            "save_draft": True,
            "preview_audience": True,
            "submit_campaign": False,
            "cancel_campaign": False,
            "read_admin_queue": False,
            "review_campaign": False,
        }
        self.drafts = []
        self.receipts = {}
        self.failure = None
        self.failure_action = None
        self.held = None
        self.hold = None
        self.submission = "30000000-0000-4000-8000-000000000001"
        self.review = {
            **draft(),
            "state": "submitted",
            "version": 2,
            "submission_id": self.submission,
            "submitted_count": 5,
            "surviving_count": 3,
            "exclusions": {"consent_absent": 2},
            "review_context": "b" * 64,
            "capacity": {"reasons": []},
            "screening_matches": [],
        }
        self.preview = {
            "campaign_id": CAMPAIGN,
            "revision_digest": DIGEST,
            "policy_version": 1,
            "grant_version": 1,
            "as_of": AT,
            "network_total": 11,
            "eligible_count": 3,
            "exclusions": {"metric_unknown": 2, "consent_absent": 6},
            "recipients_per_campaign": 7,
            "within_campaign_limit": True,
            "metric_capability": "successful_observation_unavailable",
            "submission_state": "not_implemented",
            "preview_fingerprint": "f" * 64,
        }

    def route(self, route):  # noqa: PLR0912
        path = urlparse(route.request.url).path
        if path.endswith(
            ("/admin/queue", "/admin/review", "/admin/approve", "/admin/reject")
        ):
            body = route.request.post_data_json
            self.requests.append((path, deepcopy(body)))
            if path.endswith("/queue"):
                data = {
                    "submissions": [
                        {
                            **self.review,
                            "title": self.review["content"]["title"],
                        }
                    ],
                    "has_more": False,
                    "page": body["page"],
                    "as_of": AT,
                }
            elif path.endswith("/review"):
                data = self.review
            else:
                data = {
                    "campaign_id": CAMPAIGN,
                    "version": 3,
                    "state": "approved_waiting"
                    if path.endswith("/approve")
                    else "rejected",
                }
            route.fulfill(json=data)
            return
        if "/campaigns/owned/" not in path:
            super().route(route)
            return
        body = route.request.post_data_json
        self.requests.append((path, deepcopy(body)))
        action = path.rsplit("/", 1)[-1]
        if self.hold == action:
            self.held = route
            return
        lost = self.failure == "accepted_abort"
        if lost:
            self.failure = None
        if self.failure and (
            self.failure_action is None or self.failure_action == action
        ):
            failure, self.failure = self.failure, None
            if failure == "abort":
                route.abort("failed")
            else:
                route.fulfill(status=failure, json={"detail": "conflict"})
            return
        if action == "list":
            data = {
                "drafts": self.drafts,
                "page": body["page"],
                "has_more": False,
                "as_of": AT,
            }
        elif action == "detail":
            data = self.drafts[0]
        elif action == "preview":
            data = self.preview
        elif action == "draft":
            data = draft(body["content"]["title"], body["expected_version"] + 1)
            data.update(content=body["content"], segment=body["segment"])
            self.drafts = [data]
            data = {**data, "is_current": True}
            self.receipts[body["operation_key"]] = deepcopy(data)
        elif action == "status":
            original = self.receipts.get(body["operation_key"])
            data = {
                "operation_key": body["operation_key"],
                "recorded": original is not None,
                "as_of": AT,
            }
            if original:
                data.update(
                    original_result=original,
                    current=self.drafts[0],
                    is_current=original["version"] == self.drafts[0]["version"],
                )
        elif action in ("submit", "cancel"):
            data = {
                "campaign_id": CAMPAIGN,
                "version": 2 if action == "submit" else 3,
                "state": "submitted" if action == "submit" else "cancelled",
            }
        else:
            route.fulfill(status=404, json={"detail": "not_mounted"})
            return
        if lost:
            route.abort("failed")
        else:
            route.fulfill(json=data)


@pytest.fixture(autouse=True)
def bounded_actions(page):
    page.set_default_timeout(2000)


def enter(page, network, platform="telegram", native=False):
    errors = open_app(page, network, platform, native=native)
    page.locator(".screen.active [data-campaign-workbench-open]").click()
    expect(page.locator("#campaign-workbench-list")).to_be_visible()
    return errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_owner_creates_saved_revision_before_real_aggregate_preview(
    page, platform
):
    network = WorkbenchNetwork()
    errors = enter(page, network, platform)
    expect(page.locator("#campaign-workbench-empty")).to_be_visible()
    page.locator("#campaign-workbench-create").click()
    page.locator("#campaign-draft-title").fill("SYNTHETIC local task")
    page.locator("#campaign-draft-text").fill("Actual synthetic message")
    page.locator("#campaign-segment-country").fill("KZ")
    page.locator("#campaign-segment-platform").select_option("instagram")
    page.locator("#campaign-segment-followers-min").fill("1000")
    page.locator("#campaign-draft-save").click()
    expect(page.locator("#campaign-draft-saved")).to_be_visible()
    page.locator("#campaign-draft-preview").click()
    expect(page.locator("#campaign-preview-eligible")).to_have_text("3")
    expect(page.locator("#campaign-preview-exclusions")).to_contain_text("2")
    expect(page.locator("#campaign-workbench-unavailable")).to_be_visible()
    payload = next(
        body for path, body in network.requests if path.endswith("/draft")
    )
    assert payload["platform"] == platform
    assert payload["expected_version"] == 0 and payload["operation_key"]
    assert payload["policy_version"] == 1 and payload["terms_hash"] == "a" * 64
    assert payload["segment"] == {
        "country": "kz",
        "social": {"platform": "instagram", "followers_min": 1000},
    }
    assert "campaign_id" not in payload and "owner_id" not in payload
    preview = next(
        body for path, body in network.requests if path.endswith("/preview")
    )
    assert preview["revision_digest"] == DIGEST
    page.locator("#campaign-draft-title").fill("Changed after preview")
    expect(page.locator("#campaign-preview-result")).to_be_hidden()
    expect(page.locator("#campaign-draft-preview")).to_be_disabled()
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_unknown_save_survives_reload_with_exact_key_and_original_fields(
    page, platform
):
    network = WorkbenchNetwork()
    errors = enter(page, network, platform)
    page.locator("#campaign-workbench-create").click()
    page.locator("#campaign-draft-title").fill("Original retained task")
    page.locator("#campaign-draft-text").fill("Original retained body")
    network.failure = "abort"
    page.locator("#campaign-draft-save").click()
    expect(page.locator("#campaign-workbench-retry")).to_be_visible()
    original = next(
        body for path, body in network.requests if path.endswith("/draft")
    )
    page.reload()
    expect(page.locator("#campaign-workbench-retry")).to_be_visible()
    assert sum(path.endswith("/draft") for path, _ in network.requests) == 1
    page.locator("#campaign-workbench-retry").click()
    expect(page.locator("#campaign-draft-saved")).to_be_visible()
    assert [
        body for path, body in network.requests if path.endswith("/draft")
    ] == [original, original]
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_history_survives_revoked_grant_and_admin_unavailability_is_not_empty(
    page, platform
):
    network = WorkbenchNetwork(admin=True)
    network.drafts = [draft()]
    network.settings["publisher"]["active"] = False
    network.settings["capabilities"].update(
        save_draft=False, preview_audience=False
    )
    errors = enter(page, network, platform)
    expect(page.locator("#campaign-workbench-create")).to_be_disabled()
    page.locator("[data-campaign-draft-open]").click()
    expect(page.locator("#campaign-draft-title")).to_have_value(
        "SYNTHETIC saved task"
    )
    expect(page.locator("#campaign-draft-save")).to_be_disabled()
    page.locator("#campaign-workbench-admin").click()
    expect(page.locator("#campaign-admin-unavailable")).to_be_visible()
    assert not any("/admin/queue" in path for path, _ in network.requests)
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_conflict_does_not_replay_and_refresh_preserves_unsaved_content(
    page, platform
):
    network = WorkbenchNetwork()
    network.drafts = [draft()]
    errors = enter(page, network, platform)
    page.locator("[data-campaign-draft-open]").click()
    page.locator("#campaign-draft-title").fill("Unsaved synthetic title")
    network.failure = 409
    page.locator("#campaign-draft-save").click()
    expect(page.locator("#campaign-workbench-error")).to_contain_text(
        "изменились"
    )
    expect(page.locator("#campaign-draft-title")).to_have_value(
        "Unsaved synthetic title"
    )
    assert sum(path.endswith("/draft") for path, _ in network.requests) == 1
    expect(page.locator("#campaign-draft-save")).to_be_disabled()
    assert not errors


@pytest.mark.parametrize("locale", ["ru", "en", "kk", "be", "uz"])
@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_five_locale_editor_native_controls_narrow_dark_keyboard(
    page, locale, platform
):
    network = WorkbenchNetwork(locale=locale)
    network.drafts = [draft("<img src=x onerror=alert(1)>")]
    page.set_viewport_size({"width": 320, "height": 800})
    errors = enter(page, network, platform, native=True)
    expect(page.locator("#campaign-workbench-list")).to_contain_text("<img")
    assert not page.locator("#campaign-workbench-list img").count()
    page.locator("#campaign-workbench-create").click()
    page.evaluate(
        "window.__host.wa.colorScheme='dark';window.__host.events.themeChanged()"
    )
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    page.locator("#campaign-draft-title").fill("SYNTHETIC native task")
    page.locator("#campaign-draft-text").fill("SYNTHETIC native body")
    assert page.evaluate("window.__host.wa.MainButton.visible")
    page.evaluate("window.__host.wa.MainButton.click()")
    expect(page.locator("#campaign-draft-saved")).to_be_visible()
    page.locator("#campaign-draft-text").focus()
    page.set_viewport_size({"width": 320, "height": 450})
    expect(page.locator("html")).to_have_attribute("data-keyboard", "open")
    assert page.evaluate(
        "document.documentElement.scrollWidth<=window.innerWidth"
    )
    screenshot(page, "campaign-workbench-" + platform + "-" + locale)
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_unknown_save_reload_opens_original_recovery_without_new_request(
    page, platform
):
    network = WorkbenchNetwork()
    enter(page, network, platform)
    page.locator("#campaign-workbench-create").click()
    page.locator("#campaign-draft-title").fill("Retained exact task")
    page.locator("#campaign-draft-text").fill("Retained exact text")
    network.failure = "abort"
    page.locator("#campaign-draft-save").click()
    expect(page.locator("#campaign-workbench-retry")).to_be_visible()
    page.reload()
    expect(page.locator("#campaign-workbench-retry")).to_be_visible()
    assert sum(path.endswith("/draft") for path, _ in network.requests) == 1


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_unrecognized_retained_segment_blocks_resend_and_preserves_storage(
    page, platform
):
    network = WorkbenchNetwork()
    enter(page, network, platform)
    record = {
        "version": 1,
        "actor_id": network.settings["actor_id"],
        "platform": platform,
        "path": "/campaigns/owned/draft",
        "payload": {
            "operation_key": "campaign-workbench:retained",
            "expected_version": 0,
            "policy_version": 1,
            "terms_hash": "a" * 64,
            "content": {"title": "Retained", "text": "Retained"},
            "segment": {"recipient_ids": [CAMPAIGN]},
        },
    }
    key = (
        "umc:campaign-workbench:v1:"
        + platform
        + ":"
        + network.settings["actor_id"]
    )
    page.evaluate(
        "([key,value])=>sessionStorage.setItem(key,JSON.stringify(value))",
        [key, record],
    )
    page.locator("#campaign-workbench-refresh").click()
    expect(page.locator("#campaign-workbench-storage")).to_be_visible()
    expect(page.locator("#campaign-workbench-create")).to_be_disabled()
    expect(page.locator("#campaign-workbench-retry")).to_be_hidden()
    assert (
        page.evaluate("key=>JSON.parse(sessionStorage.getItem(key))", key)
        == record
    )
    assert not any(path.endswith("/draft") for path, _ in network.requests)


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("changed", ["grant", "policy"])
def test_lost_accepted_save_recovers_receipt_after_authority_change(
    page, platform, changed
):
    network = WorkbenchNetwork()
    errors = enter(page, network, platform)
    page.locator("#campaign-workbench-create").click()
    page.locator("#campaign-draft-title").fill("Original accepted task")
    page.locator("#campaign-draft-text").fill("Original accepted body")
    network.failure = "accepted_abort"
    page.locator("#campaign-draft-save").click()
    expect(page.locator("#campaign-workbench-check")).to_be_visible()
    if changed == "grant":
        network.settings["publisher"]["active"] = False
    else:
        network.settings["policy"]["enabled"] = False
    network.settings["capabilities"].update(
        save_draft=False, preview_audience=False
    )
    page.reload()
    page.locator("#campaign-workbench-check").click()
    expect(page.locator("#campaign-draft-saved")).to_be_visible()
    expect(page.locator("#campaign-workbench-receipt")).to_contain_text(
        "подтверждено"
    )
    expect(page.locator("#campaign-workbench-pending")).to_be_hidden()
    assert sum(path.endswith("/draft") for path, _ in network.requests) == 1
    assert len(network.drafts) == 1
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_absent_receipt_never_allows_abandoning_unknown_original_request(
    page, platform
):
    network = WorkbenchNetwork()
    enter(page, network, platform)
    page.locator("#campaign-workbench-create").click()
    page.locator("#campaign-draft-title").fill("Unresolved original task")
    page.locator("#campaign-draft-text").fill("Unresolved original body")
    network.failure = "abort"
    page.locator("#campaign-draft-save").click()
    page.locator("#campaign-workbench-check").click()
    expect(page.locator("#campaign-workbench-receipt")).to_be_visible()
    expect(page.locator("#campaign-workbench-discard")).to_be_hidden()
    expect(page.locator("#campaign-workbench-retry")).to_be_visible()
    expect(page.locator("#campaign-draft-save")).to_be_disabled()
    network.failure = 403
    network.failure_action = "draft"
    page.locator("#campaign-workbench-retry").click()
    expect(page.locator("#campaign-workbench-error")).to_be_visible()
    expect(page.locator("#campaign-workbench-retry")).to_be_visible()
    writes = [
        body for path, body in network.requests if path.endswith("/draft")
    ]
    assert len(writes) == 2 and writes[0] == writes[1]


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_known_first_validation_rejection_allows_correcting_same_form(
    page, platform
):
    network = WorkbenchNetwork()
    enter(page, network, platform)
    page.locator("#campaign-workbench-create").click()
    page.locator("#campaign-draft-title").fill("Rejected initial draft")
    page.locator("#campaign-draft-text").fill("Initial draft text")
    network.failure = 422
    page.locator("#campaign-draft-save").click()
    expect(page.locator("#campaign-workbench-error")).to_be_visible()
    expect(page.locator("#campaign-workbench-pending")).to_be_hidden()
    page.locator("#campaign-draft-title").fill("Corrected valid draft")
    page.locator("#campaign-draft-save").click()
    expect(page.locator("#campaign-draft-saved")).to_be_visible()
    writes = [
        body for path, body in network.requests if path.endswith("/draft")
    ]
    assert len(writes) == 2
    assert writes[0]["operation_key"] != writes[1]["operation_key"]


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_storage_write_readback_failure_blocks_new_command(page, platform):
    network = WorkbenchNetwork()
    enter(page, network, platform)
    page.locator("#campaign-workbench-create").click()
    page.locator("#campaign-draft-title").fill("Never dispatched")
    page.locator("#campaign-draft-text").fill("Never dispatched text")
    page.evaluate("Storage.prototype.setItem=function(){}")
    page.locator("#campaign-draft-save").click()
    expect(page.locator("#campaign-workbench-storage")).to_be_visible()
    assert not any(path.endswith("/draft") for path, _ in network.requests)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_late_preview_after_edit_never_authorizes_submission(page, platform):
    network = WorkbenchNetwork()
    network.drafts = [draft()]
    enter(page, network, platform)
    page.locator("[data-campaign-draft-open]").click()
    network.hold = "preview"
    page.locator("#campaign-draft-preview").click()
    page.wait_for_function(
        "document.querySelector('#screen-campaign-workbench').getAttribute('aria-busy')==='true'"
    )
    page.locator("#campaign-draft-title").fill("Edited during observation")
    network.held.fulfill(json=network.preview)
    expect(page.locator("#campaign-draft-title")).to_have_value(
        "Edited during observation"
    )
    expect(page.locator("#campaign-draft-preview")).to_be_disabled()
    expect(page.locator("#campaign-preview-result")).to_be_hidden()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_changed_host_identity_ignores_late_preview(page, platform):
    network = WorkbenchNetwork()
    network.drafts = [draft()]
    enter(page, network, platform)
    page.locator("[data-campaign-draft-open]").click()
    network.hold = "preview"
    page.locator("#campaign-draft-preview").click()
    page.wait_for_timeout(30)
    page.evaluate("window.__host.wa.initData='different-synthetic-session'")
    network.held.fulfill(json=network.preview)
    expect(page.locator("#campaign-preview-result")).to_be_hidden()
    expect(page.locator("#campaign-draft-title")).to_be_hidden()
    expect(page.locator("#campaign-workbench-error")).to_contain_text("Сессия")
    assert sum(path.endswith("/preview") for path, _ in network.requests) == 1


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("event", ["focus", "visibilitychange"])
def test_identity_change_clears_existing_draft_without_a_new_response(
    page, platform, event
):
    network = WorkbenchNetwork()
    network.drafts = [draft("PRIVATE existing task")]
    enter(page, network, platform)
    page.locator("[data-campaign-draft-open]").click()
    expect(page.locator("#campaign-draft-title")).to_have_value(
        "PRIVATE existing task"
    )
    page.evaluate(
        "event=>{window.__host.wa.initData='changed-existing-session';"
        "(event==='focus'?window:document).dispatchEvent(new Event(event));}",
        event,
    )
    expect(page.locator("#campaign-draft-title")).to_be_hidden()
    expect(page.locator("#screen-campaign-workbench")).not_to_contain_text(
        "PRIVATE"
    )
    expect(page.locator("#campaign-workbench-error")).to_contain_text("Сессия")


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_failed_history_read_is_not_reported_as_empty(page, platform):
    network = WorkbenchNetwork()
    network.failure = 503
    enter(page, network, platform)
    expect(page.locator("#campaign-workbench-error")).to_be_visible()
    expect(page.locator("#campaign-workbench-empty")).to_be_hidden()
    page.locator("#campaign-workbench-refresh").click()
    expect(page.locator("#campaign-workbench-empty")).to_be_visible()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_identity_change_clears_open_admin_review(page, platform):
    network = WorkbenchNetwork(admin=True)
    network.settings["capabilities"].update(
        read_admin_queue=True, review_campaign=True
    )
    network.review["content"]["text"] = (
        "PRIVATE moderator-only retained content"
    )
    enter(page, network, platform)
    page.locator("#campaign-workbench-admin").click()
    page.locator("#campaign-admin-queue article button").click()
    expect(page.locator("#campaign-admin-queue")).to_contain_text("PRIVATE")
    page.evaluate(
        "window.__host.wa.initData='changed-admin-session';"
        "window.dispatchEvent(new Event('focus'))"
    )
    expect(page.locator("#campaign-admin-queue")).to_be_hidden()
    expect(page.locator("#screen-campaign-workbench")).not_to_contain_text(
        "PRIVATE"
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_return_from_terms_refreshes_context_for_existing_editor(
    page, platform
):
    network = WorkbenchNetwork()
    network.drafts = [draft()]
    errors = enter(page, network, platform)
    page.locator("[data-campaign-draft-open]").click()
    page.locator("#campaign-workbench-settings").click()
    expect(page.locator("#screen-campaign-settings")).to_be_visible()
    page.locator("#btn-campaign-back").click()
    expect(page.locator("#screen-campaign-workbench")).to_be_visible()
    page.locator("#campaign-draft-title").fill("Changed after terms review")
    expect(page.locator("#campaign-draft-save")).to_be_enabled()
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_explicit_future_submission_and_cancel_use_current_revision(
    page, platform
):
    network = WorkbenchNetwork()
    network.drafts = [draft()]
    network.settings["capabilities"].update(
        submit_campaign=True, cancel_campaign=True
    )
    errors = enter(page, network, platform)
    page.locator("[data-campaign-draft-open]").click()
    page.locator("#campaign-draft-preview").click()
    page.locator("#campaign-draft-submit").click()
    expect(page.locator("#campaign-workbench-receipt")).to_contain_text(
        "модерацию"
    )
    page.locator("#campaign-cancel-reason").fill("Actual explicit cancellation")
    page.locator("#campaign-cancel").click()
    expect(page.locator("#campaign-workbench-receipt")).to_contain_text(
        "отменено"
    )
    submitted = next(
        body for path, body in network.requests if path.endswith("/submit")
    )
    assert (
        submitted["campaign_id"] == CAMPAIGN
        and submitted["expected_version"] == 1
    )
    assert (
        submitted["revision_digest"] == DIGEST
        and submitted["policy_version"] == 1
    )
    cancelled = next(
        body for path, body in network.requests if path.endswith("/cancel")
    )
    assert (
        cancelled["expected_version"] == 2
        and cancelled["reason"] == "Actual explicit cancellation"
    )
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("action", ["approve", "reject"])
def test_explicit_future_admin_review_binds_exact_server_context(
    page, platform, action
):
    network = WorkbenchNetwork(admin=True)
    network.settings["capabilities"].update(
        read_admin_queue=True, review_campaign=True
    )
    errors = enter(page, network, platform)
    page.locator("#campaign-workbench-admin").click()
    page.locator("#campaign-admin-queue article button").click()
    expect(page.locator("#campaign-admin-queue")).to_contain_text("3")
    page.locator("#campaign-review-reason").fill("Actual explicit review")
    page.locator("#campaign-review-" + action).click()
    expect(page.locator("#campaign-workbench-receipt")).to_be_visible()
    payload = next(
        body for path, body in network.requests if path.endswith("/" + action)
    )
    assert payload["expected_version"] == 2
    assert payload["review_context"] == "b" * 64
    assert (
        payload["submission_id"] == network.submission
        and payload["revision_digest"] == DIGEST
    )
    assert (
        payload["reason"] == "Actual explicit review"
        and payload["operation_key"]
    )
    assert "decision" not in payload and "is_admin" not in payload
    assert not errors
