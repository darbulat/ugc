# Campaign visibility and delivery completion

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans. Work on the shared feature branch; each task owns separate files.

**Goal:** Show campaign actions only in relevant cabinets and complete a reliable task → moderation → Telegram → response/report flow.

**Architecture:** Reuse the runtime already merged into origin/main (6cd8f8e). Publisher grants determine sending authority, creator profiles determine consent settings, and current administrators retain configuration/moderation. Keep the dedicated single-request delivery worker and persisted policy/consent/quota checks.

**Tech stack:** Python, FastAPI, SQLAlchemy/PostgreSQL, aiogram, existing JavaScript Mini App, pytest/Playwright.

**Spec:** `docs/superpowers/briefs/umc-full-sprint/task-10-campaigns.md`, existing runtime contracts, and user request of 2026-10-27.

## Global constraints

- Own directly invited registered/verified creators only, explicit current consent, separate active moderator, published positive quotas.
- No repeated message after an uncertain or expired attempt; external send stays outside database transactions.
- Preserve existing deployment default-off switch. Complete runnable code and verification without contacting real recipients.
- Retain history for revoked publishers; hide unrelated shortcuts from role choice/client cabinets.
- Telegram and MAX management UI share access/navigation behavior; delivery remains Telegram.

## Review focus

- A stalled first attempt must not starve later queued recipients.
- Expired quota reservations must settle before new starts rather than discard valid work.
- Late provider replies must not change an expired unknown attempt into confirmed delivery.
- Account/role change must immediately remove unauthorized buttons and stale private data.
- Consent settings and recipient response return paths must remain accessible after navigation/reload.

## Tasks

- [x] 1. Delivery worker: reproduce starvation, expired-capacity and late-outcome cases with real PostgreSQL tests; fix bounded selection/settlement/deadline handling; run runtime tests.
- [x] 2. API and status integration: inspect current mounted flow, fix stale unimplemented status and any demonstrated principal/status integration faults; verify unit and PostgreSQL API paths.
- [x] 3. Cabinet UI: show workbench only for granted/former publishers and administrators in relevant cabinets; show consent settings for creators and admin configuration to admins. Remove unconditional role/client shortcuts, update misleading delivery copy, verify both hosts with role changes and real navigation.
- [x] 4. Final verification: fresh independent code review, targeted Chromium tests, full `make fix` with isolated PostgreSQL. Record commands/results and runtime enablement requirements in operations documentation.

## Execution notes

- Base: origin/main `6cd8f8e`; the original local main checkout was older (`77e749a`). Existing runtime was reused rather than rebuilt.
- Readiness and navigation are HTTP hints; commands retain current server authority. Former publishers retain history and existing consent retains an unsubscribe path after profile loss.
- Native settings/draft production routes now validate the signed principal again within the caller transaction. Eight real SQL Telegram/MAX remap regressions verified refusal and rollback of staged writes.
- Independent review reproduced an admin reason surviving account changes; fixed with browser RED/GREEN verification. Review found no remaining actionable defect after principal and recipient lifecycle fixes.
- Final Chromium run: 148 passed across campaign navigation/settings/workbench/recipient recovery and existing Mini App workflows.
- Full `make fix` with isolated PostgreSQL passed: 9,285 passed, 19 skipped, 841 deselected; coverage 98.26%. Formatting, lint, and mypy (616 source files) passed.
- The first full run was stopped for slow disk-backed migration setup. The final complete run used a dedicated disposable PostgreSQL container with tmpfs and fsync disabled. No production database or live recipient was used; transports were synthetic.
