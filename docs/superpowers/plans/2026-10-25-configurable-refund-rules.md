# Configurable refund rules implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the user's decision points 1 (selection closure/refund window) and 2 (accompaniment refund and manager adjustment) explicitly configurable through environment variables.

**Architecture:** Environment settings form a typed, immutable refund-rules document. A privileged publication command records it in a new approved financial policy, and new quotes retain that policy's snapshot. Existing policies, issued invoices and captured orders never read current environment rules. Pure calculations describe dates and cumulative refund assessments; the existing unfinished ledger-compensation workflow is outside this configuration change.

**Tech Stack:** Existing Python 3.13, Pydantic settings, SQLAlchemy/PostgreSQL, pytest.

**Spec:** User instruction in this conversation, the decision points described immediately before it; docs/product/UMC-developer-sprint-2026-10-22.html and docs/superpowers/specs/2026-10-22-financial-ledger-adr.md.

## Global constraints

- No automatic bank transfers, real payments, production changes or flag activation.
- Keep standard 500/1200/600 RUB amounts, claim/objection timing and separate 14-day hold.
- Unset configuration preserves legacy policy behavior. Partial/invalid new configuration fails explicitly; no invented financial defaults.
- Existing immutable JSON rules/quote payload store the additive snapshot; no history rewrite or capture-intent payload change.
- Stage-based customer refund percentages are explicit basis points (0..10000); absent stages and disputed work require review.
- Manager mode is retain_earned, proportional, or manual_review; assessment does not itself mutate earned balances.

## Interfaces and choices

New environment aliases:
FINANCIAL_SELECTION_REFUND_WINDOW_SECONDS (1..31536000),
FINANCIAL_SELECTION_REFUND_WINDOW_ANCHOR (item_delivered/order_closed),
FINANCIAL_SELECTION_CLOSURE_MODE (all_positions_resolved/manual),
FINANCIAL_ACCOMPANIMENT_REFUND_RATES_BPS (JSON state-to-bps map),
FINANCIAL_ACCOMPANIMENT_MANAGER_REFUND_MODE (retain_earned/proportional/manual_review).

All five are optional together; when configuring new rules all five must be explicit. An empty rates map means every accompaniment refund needs manual assessment. Example values in documentation are illustrative, not agreed or enabled business terms.

`domain.refund_rules.RefundRules` is frozen and exposes the identically named lowercase fields (without FINANCIAL_), except rates are canonical tuple pairs. `to_document()` / `from_document(value)` use exact versioned JSON with schema_version=1 and a JSON object for the rates. `FinancialConfig.refund_rules()` returns RefundRules or None.

## Review focus

- Environment changes after invoice/payment never reinterpret prior rules or idempotent retries.
- Missing, partial, malformed and boolean/fractional configuration never silently enables a financial decision.
- Both policy-loading paths and quote encode/decode preserve the same strict snapshot.
- New publication requires current active admin, explicit terms, allowlist and effective time; repeat version cannot change approved facts.
- Calculations preserve integer money, real timestamps, chronology, required closure and manual-review outcomes.

### Task 1: Configuration and pure refund decisions

**Files:** domain/refund_rules.py, config.py; new unit/application tests; config/env.example.

- [x] Add failing tests for config flat/nested/env loading and malformed/incomplete rules.
- [x] Add failing domain tests for closure modes, refund-window anchors, hold, stage refunds and manager modes.
- [x] Implement the shared typed contract, then rerun tests and quality checks.

### Task 2: Publication and immutable runtime snapshots

**Files:** financial_policy_service.py, new publication service/CLI, financial_policy.py repository, financial_capture.py, paid_item_service.py, financial_items.py; focused tests.

- [x] Add tests for no-settings compatibility, environment-backed publication, authorization/replay/conflict and persisted policy/quote round-trip.
- [x] Implement explicit publication from environment without changing activation gates.
- [x] Load the saved document in both policy-reader paths and copy it to new quotes. Preserve absence in old JSON and verify snapshot parity at capture.
- [x] Verify changed environment does not affect existing policy, quote or retry.

### Task 3: Documentation, review and complete verification

- [x] Document each variable, stage keys, units, supported choices and the publication/restart procedure.
- [x] Run focused tests including actual isolated PostgreSQL round-trip and quote/capture compatibility.
- [x] Obtain independent review and address concrete findings.
- [x] Run required make fix with existing coverage threshold; record failures/skips honestly.

## Progress

- Isolated native worktree and feature branch created; baseline 140 focused tests passed.
- Ruling: configuration selects policy inputs; it does not authorize retroactive terms changes or imply completion of R01/R05 money effects.

- Focused integrated verification: 284 passed, 99.63% across config/domain/publication/CLI; actual isolated PostgreSQL policy/quote/capture cases included. The first narrower cohort passed 262 tests but failed scoped coverage at 97.24%; meaningful boundary additions and existing linking-config tests produced the final passing gate. No threshold changes.
- Independent review: no critical/important findings; 215 pure/service tests repeated by reviewer, separate cross-review 29 tests.
- Required whole-project make fix is running; no production source changes while it executes.

- Final verification: make fix exit 0, 8807 passed / 19 skipped / 707 deselected, coverage 38389/38981 = 98.48%; formatting, Ruff and mypy (516 source files) passed. All 991 source/config pins unchanged during the run.
- Compatibility: minimum pydantic-settings 2.2.1 import failure reproduced, then removed reliance on the newer NoDecode API. Actual isolated minimum-version cohort: 228 passed; current config cohort: 85 passed. Independent review approved the small compatibility delta. The earlier whole run was explicitly interrupted before repair (3745 passed); it is not counted as a complete gate.
- Owned temporary PostgreSQL removed after verifying zero private test schemas and other client sessions. No production changes, flag activation or money movement.
