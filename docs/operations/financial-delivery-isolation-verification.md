# Financial delivery and legacy-income isolation verification

## Scope and identity

This is a verified **negative delivery / containment checkpoint**, not completion
of UMC Financial v1, Task 25, Task 23, or the 52-task implementation plan.

- Base: `e0c4fad669ff584f35cbe3c8329e72041ec96f47` (capture/journal draft PR #151).
- Tested runtime/test/config Git tree: `d9d96b17932cbfa45302d1921b9743b5de0c9551`.
- This verification document is added after those gates; the tested source,
  tests, configuration and workflow blobs are unchanged.

## Implemented contract

- The real capture path emits a durable delivery request. Production factories
  and the existing processor route it to a separate financial owner.
- The typed financial router intentionally raises `FinancialHandlerUnreadyError`.
  The processor persists retry/error and ultimately FAILED, without monetary
  mutations or pretending that a business handler succeeded.
- Legacy delivery excludes the whole `financial.*` namespace. Financial delivery
  owns that namespace except exact `financial.capture_intent`, an invoice control
  record excluded from all delivery lifecycle operations.
- Receipt identity/type/payload survive retry exhaustion and retention. Financial
  cleanup does not delete either financial identities or unrelated legacy rows.
- Memory owners share the original event and lease dictionaries by identity;
  existing constructors and explicit financial-owner precedence remain intact.
- Both legacy referral discovery queries filter `financial_version IS NULL`
  before LIMIT; both shared recorders reject any non-None financial version
  before effects. NULL-version legacy positive/idempotent behavior is preserved.

## Final executed checks

- Full suite: **4345 passed, 19 skipped, 18 deselected**, 106 warnings, 759.20s.
  Pytest exit 0 and fail-closed wrapper exit 0.
- Coverage XML: **23404 / 23861 executable lines = 98.0847407904%**, 457 missed.
  Exact integer threshold check `covered * 100 >= executable * 98` passed.
  Coverage configuration, exclusions and required floor were not changed.
- JUnit: **4364 cases, zero failures/errors**. All **288 mandatory PostgreSQL
  (classname, name) pairs** are present among passed cases, not skipped; all nine
  authoritative-transfer guard cases also passed.
- Standalone owned Docker/PostGIS: **307 passed**, 4 warnings, 546.72s. Includes
  all 288 PostgreSQL cases plus replay tests; guarded migration smoke passed.
- The test-only Compose project was removed. Independent project-label queries
  confirmed zero remaining containers, networks and volumes. Teardown printed
  `Error while Stopping` before successfully removing the test container and
  network; its cause is not established, and final absence was checked directly.
- Focused integration run before freezing: **250 passed**, including 32 PostgreSQL
  cases; Ruff/format (542 files), mypy (300 source files), diff-check passed.
- Fresh independent static review of all 13 changed runtime/test files: **PASS**,
  no introduced caller-reachable P1/P2 found. Static approval is not runtime or
  production-readiness approval.
- Source and index were independently checked against the frozen tree after
  both long gates, including absence of unexpected untracked inputs.

The local full gate used a 60-second per-test execution timeout, matching the
focused and standalone runs. This does not establish remote CI results; those
must be checked against the published head separately.

## Evidence boundaries

- Held-claim exclusion uses distinct real PostgreSQL backends while the first
  transaction remains open. Committed abandoned-lease recovery proves fresh
  exclusion followed by recovery after aging only `claimed_at`; neither is an OS
  process-kill or external exactly-once proof.
- State helpers require every `ledger_schema.NAMES` table (including
  `rate_snapshots`) plus assignments and payment/item/allocation/order state.
  Empty immutable-history tables establish no insertion, not preservation of
  populated journal history. Request lifecycle fields intentionally change;
  immutable request identity/type/payload and the complete invoice control row
  are asserted separately.
- AC43 starts with actual capture and explicitly synthetic later CLOSED staging;
  natural completion and public callback coverage are not claimed.
- Fresh memory parity has its own three observed sequential behavioral RED/GREEN
  cycles (factory retry, retention, stale lease ownership). Seeded memory events
  prove factory/processor wiring, not public memory capture or SQL durability.
- Positive monetary/snapshot consumers and durable inbox Task 26 remain absent.
  Kafka-disabled factory construction is not proof of Kafka-disabled worker
  startup. Grade/cutover provenance, full assignment/return lifecycle, refunds,
  payout integration, legal/UI launch gates and the remaining plan stay open.
- No merge, deployment, production migration, real payment or business
  notification is authorized by publication. Financial flags remain disabled.
