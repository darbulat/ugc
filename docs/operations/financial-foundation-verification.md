# Financial v1 foundation — verification and scope

This is the next implementation checkpoint after stage A (PR #149), not a
completed Financial v1 rollout. It implements the foundation portions of plan
Tasks 11–15 and ledger storage Task 18. Capture Task 16, assignment lifecycle,
ledger application commands, payout/refund operations, and financial UI are
not part of this checkpoint.

## Implemented

- Typed minor-unit money, financial identities, timestamps and calendar/rate
  contracts, with explicit validation rather than floating-point commissions.
- Independent default-off core/new-order/payout gates; approved policy requires
  actual identity, effective date, refund parameters and published terms.
- Migrated policy/item/assignment/allocation persistence and database invariants;
  no inferred historical financial backfill or implicit legacy conversion.
- Explicit application quote command: 30 item snapshots, prepayment service
  selection and agreed deadline/contact references, atomic order/quote creation,
  stable command retries, and rejection of changed duplicate payloads.
- Actual Container wiring for the quote repository/service and a typed persisted
  policy reader through the existing transaction manager. Disabled policy loads
  refuse before SQL. The reader never derives approval from a request body.
- Append-only ledger storage, immutable snapshots and scoped references tying an
  assignment/snapshot/obligation to the same paid item and assignment version.
- Non-destructive migration refusal: writer-excluding table locks precede history
  checks, and committed history must survive a competing downgrade.

The policy reader's explicit stored JSON fields are `allowed_clients` (a list
of nonzero UUID strings) and `terms_reference` (a nonempty reference). Refund
window is read from the persisted column. These fields do not create approved
legal text, a refund window, or a policy-approval API. Loading policy alone does
not authorize a quote/capture; command-specific eligibility checks remain.

## Executed checks

Canonical application suite against dedicated local test PostgreSQL/private
migrated schemas:

```sh
pytest -m 'not e2e' --require-financial-postgres \
  --cov=ugc_bot --cov-config=pyproject.toml --cov-fail-under=98 \
  --cov-report=term-missing:skip-covered --cov-report=xml
```

- **4197 passed, 19 skipped, 18 deselected**, exit **0**.
- Coverage **98.04%**; required threshold remains **98%**.
- Ruff check: passed. Ruff format check: **512 files already formatted**.
- Mypy: **no issues in 293 source files**. `git diff --check`: passed.

Standalone `docker-compose.financial-test.yml` in a fresh owned project:

- Built test/migration images and verified database readiness.
- Guarded migration smoke: exit **0**.
- Complete `tests/postgres_financial` suite: **185 passed**, exit **0**.
- Owned containers/network removed after completion; cleanup independently
  checked by project labels. No production Compose overlay, env-file, bind mount,
  published port or shared/external network was used.

The canonical and standalone PostgreSQL counts are different executions, not
additive evidence of distinct tests. SQLite is not used to certify financial
locking, migrations, replay/storage integrity or concurrency.

## Independent review and corrected regressions

Initial source review found B-REV-01: `financial_items.downgrade` observed an
empty history before excluding concurrent writers. The fix locks all four
financial tables plus orders/payments before any check/DDL in the same migration
transaction. Four real independent-session regressions cover policy insertion,
first captured amount, payment version and order version; they verify observed
blocking, writer commit, downgrade refusal, retained history and unchanged
revision. No immutable trigger was disabled for their setup.

Independent follow-up static review read the relevant complete source/tests and
reported **passed=true**, with empty security and logic blocker lists. It also
reviewed the real Container/reader wiring and fail-closed gates. The reviewer did
not execute SQL/tests or establish production-role privileges; execution results
above are separate parent runs.

The existing legacy-case downgrade test now compares the revision with its
observed pre-operation value instead of an obsolete hardcoded head. Its existing
history/released-state preservation assertions remain.

## Still gated / not claimed

- No public Financial v1 quote endpoint or completed financial UI.
- No provider capture, ledger issue/transfer/replay consumers, or real bank facts
  introduced by this checkpoint.
- Runtime SQL role separation remains a deployment requirement; schema-owner
  fixtures do not prove effective deployed privileges.
- Legal terms and refund-window approval remain explicit launch gates.
- All new financial flags remain default-off; no real payments/notifications,
  production migrations, deployment, merge or rollout approval occurred.
- Stage A's previously reported CI results do not establish this checkpoint's CI;
  inspect this checkpoint's actual PR head/workflow runs separately.
