# Legacy financial case review (Task05)

This is an authenticated MiniApp operator API, not the generic interaction editor.
Only a server-resolved user with the actual database `User.admin = true` may list
or review cases. Use the normal signed Telegram/Max `init_data` and `platform`;
never send an actor ID or an admin flag. Examples below omit the signed credentials.
No v1 finance flags, new ledger, payout execution, or external bank calls are enabled.

## Find and inspect

`POST /api/finance/legacy-cases` with `init_data` and optional fields:

- `interaction_id`: exact UUID lookup, useful for reloading a stale case.
- `limit`: 1–200, default 200.
- `after`: last returned `interaction_id`; UUID keyset pagination in ascending order.
- `released`: omit for all, `false` for blocked, `true` for released.

The response is an array with source/cause, version, released state, wallet
user/currency pairs, and ordered audit history. Continue with the final UUID until
a page is empty (do not assume a short page proves completion). Keep the same
filters throughout a scan. Historical ISSUEs without a case are materialized in
bounded batches during reads. Concurrent inserts/reopening below your cursor may
require a fresh scan from the beginning; this is not a snapshot/export endpoint.

## Decide

`POST /api/finance/legacy-cases/{interaction_id}/review` accepts:

```json
{
  "init_data": "<current signed MiniApp initData>",
  "expected_version": 1,
  "command_id": "<fresh UUID for this exact command>",
  "decision": "keep_blocked",
  "reason": "Evidence insufficient; awaiting reconciliation",
  "confirmed_result": false
}
```

Use `keep_blocked` whenever evidence is incomplete or a money adjustment is needed.
For `release_no_adjustment`, independently verify the legacy delivery/result and
unchanged financial basis, document the evidence in a nonblank reason, and set
`confirmed_result: true`. Unknown/negative income, unknown paid amounts, and an
unreconciled wallet prevent release. Do not invent zero amounts or edit old paid
rows to bypass these checks. Financial adjustments require a future supported path.

A release affects only this case; other cases on the same wallet remain blocking.
It does not rewrite income, payouts, reserves, or interaction status. Source changes
can reopen a released case and increment its version. Inspect history before retrying.

- 401: invalid/expired signature; obtain fresh MiniApp credentials.
- 403: insufficient actual DB privileges; do not retry with body role overrides.
- 422: invalid request, missing reason, or forbidden actor/admin fields.
- 409: stale version, conflicting command reuse, or unsafe basis. Reload and inspect.

Retry an uncertain transport outcome using the **identical** command ID and payload;
that returns the recorded decision without a second audit event. For a changed
decision/reason/version use a new command ID after reloading. Review is audited with
the actual DB admin identity. System source events have no human actor.

## Rollback

The unpublished `legacy_financial_guard` migration includes cases and audit events.
Downgrade takes ACCESS EXCLUSIVE locks on all three legacy safety tables before
checking them. It refuses to delete any case history (even released cases), or any
remaining guard. Preserve the database and use a forward migration; do not delete
history to force rollback. Parent branch guard/admin lifecycle hardening must be
merged and verified separately before claiming all legacy mutation entrypoints safe.
