# Financial capture — isolated verification checkpoint

## Scope

Task 16 on `feat/umc-financial-v1-lifecycle`, stacked on foundation commit
`bc12940cfc10b507781bb2836b423e1ff69e0233` (draft PR #150).
This is not completion of Financial v1 or Tasks 17–52.

The implementation connects protocol-authenticated Telegram receipts to durable,
provider/account-scoped invoice and capture identities. The caller transaction
owns payment, paid-item timestamps, exact component allocations and one client
snapshot request. No monetary snapshot consumer, journal issuance, refund or
payout writer is activated by this checkpoint.

Telegram `Message.date` is protocol-message time, **not bank settlement time**.
Fixtures use synthetic messages, policies, identities and money amounts; none is
proof of an actual provider charge or a bank fact.

## Final execution

The fresh full non-E2E suite, with real isolated PostgreSQL required, returned:

- **4228 passed, 19 skipped, 18 deselected**, 656.31 seconds.
- Coverage **98.01%**: 22,901 covered of 23,366 executable source lines.
- Required coverage remained **98%**; no exclusion changes.
- Independent JUnit validation: 4,247 reported cases, **0 failures/errors**,
  **215 passed PostgreSQL cases**.
- Ruff: **518 files formatted**, lint clean; mypy: **295 source files**, clean.

The external verification driver also checked exact integer coverage counts and
JUnit results, independently of the pytest/process exit status:

- `/tmp/ugc-financial-capture-final-gate.py`
- `/tmp/ugc-financial-capture-final-result.json`
- `/tmp/ugc-financial-capture-final-gate.xml`
- `/tmp/ugc-financial-capture-final-junit.xml`

These paths are local execution evidence, not checked-in prerequisites.

### Earlier failure, not concealed

The previous full run passed 4,221 tests but reached only **97.97%** coverage.
It was rejected. Its printed coverage failure conflicted with the process
wrapper's reported exit 0; root-cause investigation remains separate. A green
process status was not accepted as proof of coverage compliance.

Seven added real-PostgreSQL rejection-integrity cases exercised owner mismatch,
empty/changed account scope, legacy/missing-quote orders and invalid receipt
times. They assert preserved pending payment, unchanged invoice identity,
preserved item count and uncaptured items, and no allocations/snapshot request.
These are regression tests of existing guards, **not new runtime behavior or a
claim of a new behavioral RED/GREEN implementation cycle**.

A diagnostic append reached 98.01%; it did not replace the fresh full-suite gate
reported above.

## Standalone Docker/PostGIS

Only `docker-compose.financial-test.yml` was used, with an explicit empty env
file, unpredictable owned project names, no published ports/bind mounts/external
networks and an independently inspected internal network. Live application and
production Compose services were not used.

- Full financial PostgreSQL suite: **208 passed**, 403.00 seconds.
- Supplemental final rejection-integrity file: **7 passed**, 31.25 seconds.
- Both projects completed guarded migration smoke and label-verified cleanup.
- The runtime source was verified unchanged between these two runs. The second
  image added the final seven rejection-integrity cases.

Local manifests/results:

- `/tmp/ugc-financial-capture-compose-project.json`
- `/tmp/ugc-financial-capture-compose-result.json`
- `/tmp/ugc-financial-capture-negative-compose-project.json`
- `/tmp/ugc-financial-capture-negative-compose-result.json`

## Review and limits

Independent read-only integration review of the runtime/DI delta passed with no
P1/P2 blockers. Report: `/tmp/ugc-financial-capture-integrated-review.json`.
It was a static source review, not a test execution or production authorization.
The seven additional regression tests were added after that static review.

Retained HTTP authentication tests passed separately (2 cases): missing/wrong
Telegram webhook secret returns 403; empty configured secret refuses startup.
They use isolated local HTTP/test dependencies, not live Telegram requests.

All financial flags retain false defaults; merchant account remains empty in the
example configuration. Existing persisted synthetic invoices were tested across
sales pauses without mutating production settings. Quote creation/DI is not
activation of a Mini App financial endpoint or financial UI.

No merge, production deployment/migration, real invoice/payment/refund/payout,
provider call or real notification was performed. Journal integrity fixes and
Task 17 work remain separate from this capture checkpoint. Missing future
writers, legal launch approvals and the rest of the 52-task plan remain gates.
