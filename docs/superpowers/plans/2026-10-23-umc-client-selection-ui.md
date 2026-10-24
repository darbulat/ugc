# UMC Task9d own-client intake and selection UI

Root approved the narrow design before production edits. No subagents, commits, live sends, deployment or financial flag activation.

Use the existing supplied UMC system: white #ffffff/card #f5f5f5/ink #141414/lavender #d2c4ff/muted #5e5e66; supplied dark tokens; Oswald headings, IBM Plex Sans body with existing Kazakh fallback. Keep the existing logo, pixel edge, screen shell, safe areas and native controls. New `.umc-selection` namespace only; no partner-module edits.

Add a distinct own-client “30-creator selection” dashboard entry without removing the existing legacy form. Two dedicated screens: a lavender intake form and own-order selection status. Mount after collaboration, script after partner; UI partner agreed these anchors.

Before implementation, real production browser/ASGI tests observed missing entry/controller RED (4 failures). Signed actual-PG policy-list tests also start at missing endpoint RED.

Intake reads only actual eligible published policies from signed `/financial/orders/policies`. Current active advertiser/country, RUB, approved/effective immutable policy, allowlist, actual terms and refund duration remain server facts. None available and core/new-order pauses are explicit; no hardcoded policy version. Exact stored schedule drives a labelled preview, but success and amounts come from the persisted creation response only.

Inputs: actual policy, product/brief, direct creator honorarium, aware due date shown with local timezone, contact, self-service/with-manager and optional selected position subset. All-manager means 30 positions. No client-authority actor/manager IDs, financial amounts/rates/approval/provider commands. No fabricated invoice/pay action.

Before first send, save one secure operation key and frozen token-free payload in sessionStorage scoped by actual current user/platform. Disable duplicate sends. Uncertain outcome retains the same body/key across reload and offers explicit retry only; no automatic resubmit, optimistic success or different new draft. Definitive validation failure permits corrections. A persisted receipt shows actual 500/1200 components and requested/unpaid lead, with direct honorarium excluded.

Selection signed read uses root’s mounted `/financial/orders/{id}/selection`. Stable paid positions are shown once. Current `delivered_at` is shown only for actual current-assignment acceptance; original `fulfilled_at` and historical accepted deliveries are separate. Unknown remains unknown, not delivered or failed. Show actual stored components/currency and waitlist count; paused historical reads remain available. No provider references or outcome commands.

Narrow existing order list addition: expose actual financial_version, suppress legacy bot payment link on v1, add row dataset so the dedicated controller adds an own-client selection entry. Preserve all other legacy IDs/workflows. Five locales ru/en/kk/be/uz, safe text/HTTP(S) links, 320px dark/light, keyboard/focus/native back and actual collaboration navigation where facts allow.

Verification: ASGI static mounts and signed policy authority/filter/gates with actual PostgreSQL; browser production templates with only host/API boundary synthetic, exact payload and pending/retry/reload; replacement delivery semantics; invalid/ambiguous links; safe DOM, localization, responsive screenshots; existing design/social/collaboration regressions. Root retains one shared fresh global98%/make fix/commit gate. Report exact evidence and limits under /tmp/umc-full-sprint-reports/task-9d-report.md.
