# Campaign and correction Mini App implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development to implement the independent boundaries below; use executing-plans for integration. The existing sprint document, supplied UMC design system and current request authorize implementation.

**Goal:** Make campaign drafts/audience preview and supported selection refund review usable in Telegram and MAX.

**Architecture:** Vanilla shared controllers consume signed FastAPI POST APIs. Campaign screens use existing draft/audience services and explicit capabilities. A narrow correction reader/API/factory exposes the existing authoritative correction service without inventing financial execution.

**Tech Stack:** Python/FastAPI/SQLAlchemy/PostgreSQL, HTML/CSS/JavaScript, pytest/Playwright.

**Spec:** Existing sprint acceptance criteria and `../briefs/umc-full-sprint/task-6c-corrections-design.md`; user request: «Доделай интерфейсы рассылок и корректировок/возвратов».

## Global constraints

- Match supplied UMC tokens, fonts, logo and current shell; both messenger templates and ru/en/kk/be/uz.
- Money is canonical decimal minor-unit strings at every wire boundary; no browser Number conversion.
- Use existing-only signed native identity for correction ingress and revalidate current ownership/admin authority inside the transaction.
- Unknown command result retains its operation key. Retry is explicit and preserves exact intent. No automatic new command after lost response.
- No auth, bank or protected evidence in browser persistence/URLs. Owner DTOs exclude admin evidence.
- Correction match remains `applied=false`, `awaiting_assessment`; unavailable campaign submission/delivery remains explicitly unavailable.
- No live sends, bank actions, activation, deployment or invented business timing. No migration needed for this bounded API/UI layer.
- Preserve coverage floor 98% and existing checks; do not exclude changed modules or historical tests.

## Review focus

- Late response after navigation or identity change cannot display another scope or trigger a command.
- Unknown result cannot be replayed with edited fields under the same key or silently receive a new key.
- Selected-position preview hash must represent exactly the submitted subset; owner cannot target another order.
- Original receipt and current state stay distinct; manual observation/match never implies money returned.
- Loading, genuine empty, error and unavailable remain distinguishable; 320px, dark theme and native Back/Main stay usable.

### Task 1: Campaign workbench

Owner: campaign worker. Files: `miniapp/umc-campaign-workbench.{js,css}`, `miniapp/campaign_api.py`, focused tests.

- [x] Write and run failing browser/API tests for own drafts, saved-revision preview, conflicts, explicit retry and capabilities.
- [x] Implement list/editor/save/detail/preview and admin availability states against actual contracts, all locales.
- [x] Run focused tests and inspect rendered screenshots for both hosts.

### Task 2: Correction API and reader

Owner: correction backend worker. Files: new correction API/wire/view service/factory, repository read seam, DI/types, focused tests.

- [x] Write/run failing native authority, subset preview, wire privacy and replay tests.
- [x] Add signed context/list/orders/preview/detail/operation status and the four existing commands; every command delegates to the authoritative service.
- [x] Add real factory/DI. Run focused unit and, with exclusive root-coordinated ownership, private PostgreSQL integration checks.

### Task 3: Correction interface

Owner: correction UI worker. Files: `miniapp/umc-corrections.{js,css}`, focused browser/static tests.

- [x] Write/run failing owner request/admin review/manual fact/match/unknown-result tests using real local assets.
- [x] Implement own/admin flows against Task 2 contracts; use request contexts, strict string money and protected transient fields.
- [x] Verify locales, native/fallback controls, stale responses, XSS/privacy and truthful financial status in both hosts; inspect screenshots.

### Task 4: Integration and acceptance

Owner: root. Files: both HTML templates, `miniapp/api.py`, evidence artifacts and this plan.

- [x] Mount exact controllers/styles/empty screens and correction router; verify actual mounted bytes and endpoints through integration/browser tests.
- [x] Review independent implementations for contract drift, authority, UI states and sensitive storage.
- [x] Run format/lint/type checks and meaningful combined regression/coverage; repair findings and review current changes.
- [x] Record actual evidence and remaining unsupported backend business stages without promoting them to done.

**Final acceptance (2026-10-24):** original `make fix` exit 0; 8586 passed, 19 skipped, 707 e2e deselected; whole coverage 38093/38682 (98.4773%). Separate final combined browser: 540 passed. Whole 12 changed Python runtime modules: 2369/2395 (98.9144%). Source/config unchanged through verification; private PostgreSQL released cleanly. Fresh independent review findings closed. Detailed evidence: `/tmp/umc-full-sprint-reports/task-campaign-correction-ui-current-report.json` and `task-campaign-correction-ui-current-freeze.json`. Campaign moderation/delivery and positive refund compensation remain unsupported, as required by current capabilities.
