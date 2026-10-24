# Task 10a: campaign policy, publisher grants and creator consent

Approved parent design: `task-10-campaigns.md`. This slice implements configuration and consent only; it creates no delivery transport, jobs, financial outcome, subscription or pilot claim.

Use append-only policy, publisher and consent event streams plus actor-scoped immutable command receipts. Current versions are derived from committed events. Policy publication contains full localized text, a required default locale, an explicit terms version and canonical content hash, and every required positive numeric limit; there are no business quota defaults. Suspension appends an event. A publication version is the consent reference; replacing a publication requires explicit consent again. Reusing a terms version for different text is rejected.

Current active UMC administrators publish/suspend policies and grant/revoke publishing for an existing account independently of staff assignments. All admin commands recheck current authority, including replays. Signed creator consent derives the actual direct inviter and canonical confirmed Instagram identity from SQL; request bodies never select an inviter or assert ownership/verification. Grant requires an active owner publisher, active creator, current publication and real private Telegram contact. Revocation uses the creator's own last consent stream and works while policies/grants/accounts are paused or identity/binding eligibility was lost. No registration consent is backfilled.

Writes use sorted User share barriers followed by a dedicated campaign advisory transaction lock, then source checks and expected stream version. No wallet/item locks or network calls occur. Reads set REPEATABLE READ READ ONLY before querying. Expose only current own grant/consent and actual inviter's safe label; admin account lookup is separately authorized and paged without contacts. Actor-scoped operation keys bind exact intent; conflicting reuse fails, old replays retain original result with current-state flags rather than replaying effects.

Migration: `campaign_foundation_v1`, child `paid_selection_delivery_v1`. Root approved narrow model registration, repository/service factory, signed router inclusion, both HTML mounts/script and namespaced CSS ownership. Follow-on M02 worker must add its separate default-off flag before any transport construction.

- [x] RED: real PostgreSQL foundation tests for current admin authority, no default consent, current inviter/verified identity/contact, exact publication/hash, suspend/unsubscribe, policy/role loss and command conflicts.
- [x] GREEN: new domain/ports/service, immutable schema and SQL adapter; signed Telegram/MAX API with actual production factories.
- [x] Concurrency/retention: simultaneous grant/consent commands, stale expected versions, User authority barrier, read-only repeatable snapshot, UPDATE/DELETE/TRUNCATE rejection, safe migration roundtrip and refusal to discard history.
- [x] UI: real settings entry for all roles, current terms/limits and own publisher status, creator opt-in/unsubscribe, and active-admin publish/suspend plus paged existing-account grant/revoke screens. Preserve unknown operation keys for explicit retry and refresh on conflicts; no unimplemented task/send controls.
- [x] Browser/ASGI: exact signed payloads and authoritative capability gates in both host shells; locale/theme/keyboard/320px evidence and carried UI regressions; actual ASGI routes/static bytes.
- [x] Scoped Ruff/mypy, sysmon coverage at unchanged 98% floor, report actual checks/limitations; root retains full shared gate and broad M02 completion.

Implementation handoff: `/tmp/umc-full-sprint-reports/task-10a-report.md`. Root owns independent review, the next M02 audience/moderation/worker stages and the shared final gate. No broader Task 10 completion is claimed.

Independent-review correction: allow now requires the opaque server-derived `consent_context` from the displayed settings, covering actor/IG/exact inviter/immutable binding observation. Pending retries retain that original context; stale bindings conflict. Exact admin UUID lookup includes inactive retained grant holders with safe status/capabilities; grant remains active-only. Recheck handoff: `/tmp/umc-full-sprint-reports/task-10a-review-fixes.md`. No migration or 10b work.
