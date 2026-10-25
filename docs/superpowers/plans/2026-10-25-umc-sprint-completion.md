# UMC remaining sprint implementation plan

> Execute the approved original design with parallel module ownership and independent integration review.

**Goal:** Finish the technical remainder of the UMC sprint, excluding F01 automatic bank transfers.

**Architecture:** Extend existing services, immutable financial journal, authenticated Mini App routes and durable outbox. Keep stored payment policies authoritative. Commercial evidence records real manually reviewed payments; no test record constitutes a real paid pilot.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy/PostgreSQL, existing HTML/JS UMC design system, pytest/Playwright.

**Spec:** `../specs/2026-10-23-umc-product-sprint-design.md` and `../../product/UMC-developer-sprint-2026-10-22.html`, including amendments. The new exclusion supersedes the original F01 scope.

## Constraints and review focus

- Preserve integer amounts, immutable snapshots, shared recipient lock order, idempotency and transactional journal/outbox.
- Prices remain 50000 selection, 120000 accompaniment and 60000 manager reward in RUB minor units. No invented bank or legal facts.
- No live sends/deployment during development. No silent post-paid offsets. Expiry and automatic tax deductions remain disabled.
- Verify stale versions/roles, duplicate/reordered/concurrent commands, partial delivery/refunds, failed delivery and ownership on actual PostgreSQL.
- A tariff publication is configuration, not payment evidence; real pilots, legal decisions and physical-device acceptance remain external facts.

## Parallel tasks

### Finance (R01,R04,R05,M03,P01)

Owned by finance agent: domain/services/ports/SQL finance files and focused tests. Root owns shared factories/routers.

- [x] Persist selection closure, derive refund deadline from stored rules, release client grounds only after closure/window/14d hold.
- [x] Add reviewed current-admin dispute decisions with evidence/version, preserving immutable history and financial blocking.
- [x] Implement compensation, replacement/refund funding barriers, reserved payout blocks, paid debt and real recovery.
- [x] Prove 30/25/5 through actual runtime, replay/concurrency/rollback and independently review.

### Campaigns (M02,A01)

Owned by campaign agent: campaign services/adapters/runtime schema/router/workbench and tests.

- [x] Connect submit/moderation persistence and current authenticated routes; reserve quotas atomically.
- [x] Implement own opted-in network delivery, cancellation, recipient response and report using durable provider-result evidence.
- [x] Add scoped attributed view/click/lead/action events, idempotent manual source import and CPV/CPA/CPL reports with unknown denominators.
- [x] Verify no foreign network exposure, revoked consent/roles, retries and real SQL races.

### Partner cabinets (R03,M01,G01)

Owned by partner agent: own DTO/projection, partner JS and override API/UI tests.

- [x] Visible home referral link/rates; safe missing-confirmation reasons; own-network identity/activity and manager successful-count breakdown.
- [x] Current-admin side/period/reason override UI and audited technical referral-binding correction without history rewrite.
- [x] Verify permissions, old users, published snapshot parity and UI localization.

### Intake and commercial operations (O01,S01,P02,L01)

Owned by root: intake targeting, lead acceptance, subscription domain/service/SQL/API/UI and integration wiring.

- [x] Add validated structured targeting to actual intake, preserve idempotent persisted order facts and existing fixed approved 30-position package.
- [x] Add admin lead queue/review with immutable acceptance events and existing multi-manager assignment linkage.
- [x] Implement versioned published tariffs, actual reviewed manual payment proof, activation/renewal/expiry/cancel and serialized quota usage; gate automation on real pilot evidence.
- [x] Keep legal/expiry/tax gates explicit; show true financial status and preserve real approval/accepted-term references.

## Integration and acceptance

- [x] Assemble single migration chain: existing head →00f0_campaign_runtime→00e0_financial_completion→0110_commercial_completion→0111_lead_review→0112_referral_binding_audit→0113_campaign_analytics→0114_refund_replacements→0115_debt_recovery→0116_manual_grants→0117_financial_reviews→0118_financial_review_restore→0119_accompaniment_prior.
- [x] Mount real routers, builders and scheduler/worker hooks; no capability claims backed only by dormant contracts.
- [x] Run focused tests, isolated PostgreSQL migrations/races, browser journeys, full `make fix` with unchanged 98% floor and independent final review.
- [x] Update requirement evidence honestly, separate code completion from external pilot/legal/device acceptance, commit verified changes on the existing feature branch.

Final verification: full `make fix` passed with required isolated PostgreSQL: 9260 passed, 19 skipped, 98.26% coverage. Ruff, format checks and mypy (615 source files) passed. Chromium cohort: 197 passed. Independent review findings were resolved and rechecked. Final code and tests remained frozen throughout the complete gate.

Operational instructions and external acceptance boundaries: `../../operations/umc-sprint-completion.md`. Automatic bank transfers remain excluded; paid pilots, legal/accounting decisions and physical-device acceptance require real external evidence.
