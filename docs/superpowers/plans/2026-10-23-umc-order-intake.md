# UMC S01 Order Intake Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans in this shared worktree. No subagents or commits; root owns the final whole-branch gate.

**Goal:** Authenticated self-service/with-manager v1 order creation atomically persists quote, original intake receipt, optional unpaid accompaniment lead and durable admin notification queue.

**Architecture:** New intake service owns a caller transaction and invokes the existing OrderService financial method with an optional caller session. New immutable request/lead facts are separate from notification jobs/attempts/outcomes. One-shot provider sends occur after committed preparation with no checked-out DB session. No assignment/reward is inferred from requesting accompaniment.

**Tech Stack:** Python 3.13, existing FastAPI/SQLAlchemy/PostgreSQL, signed Telegram/MAX Mini Apps, pytest.

**Spec:** docs/product/UMC-developer-sprint-2026-10-22.html S01 amendments; full sprint design; root approved this exact boundary in chat.

## Global Constraints

- Existing financial core/new-order flags remain default false; real approved/allowlisted policy only.
- 30 positions, selection50000 each; selected accompaniment120000 each; all-manager bundle170000 per position. Creator honorarium stays direct and outside platform quote.
- Current authenticated client identity/advertiser role, currency and policy are read server-side. No request-supplied approvals, actor/manager IDs, sum or rates.
- User NO KEY UPDATE precedes operation/order locks; no wallet/financial consumer/HTML modifications.
- New migration accompaniment_leads_v1 follows financial_work_entitlements_v1.
- Keep98% coverage; no no-cover additions; root final make fix/commit.

## Review Focus

- Same click key with later clock returns original dates/IDs, changed normalized payload conflicts; other users cannot replay another receipt.
- Quote/lead/outbox/commit failure leaves no partial order; failed notification never erases a lead or creates management money.
- Current role/admin/contact changes cannot send to request-selected or stale recipients; unknown transport/crash cannot auto-resend.
- Disabled flags, missing approvals, expired due and invalid selected ordinals reject before persistence; no fabricated invoice or approval.
- Concurrent clicks/workers and rollback serialize on actual PostgreSQL; transport I/O uses no active DB session or row lock.

## Tasks

1. Write RED service and PostgreSQL cases for modes, subset prices, replay/conflict, auth/flags/policy and whole-transaction rollback. Implement domain DTOs, ports, intake service and SQL persistence; add optional OrderService session while retaining old transaction callers. GREEN existing quote tests too.
2. Write RED notification cases for current server admins, committed preparation, acceptance/failure/unknown, crash/retry, source proof and concurrent worker leases. Implement dedicated durable queue/attempt/outcome worker and transport bridge reusing one-shot receipt adapters. No financial entitlement is emitted.
3. Write RED signed Telegram/MAX API and real container/SQL path. Implement focused /financial/orders router, isolated factory/model registration, default-off worker entrypoint/runtime hooks. HTML remains another owner's scope.
4. Run focused suite, owned lint/type/format and actual PG concurrency/rollback. Run one broad non-E2E regression, report all failures and scoped/global coverage truthfully. Write report under /tmp/umc-full-sprint-reports/ with actual RED/GREEN commands/results, interfaces and remaining product/UI/external conditions.
