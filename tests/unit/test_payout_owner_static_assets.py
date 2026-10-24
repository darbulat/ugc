"""Production payout assets and their exact, nonsensitive helper contracts."""

import asyncio
import importlib
import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path

import httpx
import pytest

MINIAPP = Path(__file__).resolve().parents[2] / "src/ugc_bot/miniapp"
ASSETS = (
    "umc-payout-money.js",
    "umc-payout-state.js",
    "umc-payouts.js",
    "umc-payouts.css",
)
HOSTS = (
    ("telegram_webhook_app", "app.html"),
    ("max_webhook_app", "max_app.html"),
)


class _PayoutTemplate(HTMLParser):
    """Collect only integration points used by the shared controller."""

    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[dict[str, str | None]] = []
        self.styles: list[dict[str, str | None]] = []
        self.mounts: list[dict[str, str | None]] = []
        self.mount_content: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if self._depth:
            self._depth += 1
            self.mount_content.append(tag)
        elif attributes.get("id") == "screen-payouts":
            self.mounts.append(attributes)
            self._depth = 1
        if tag == "script" and attributes.get("src"):
            self.scripts.append(attributes)
        if tag == "link" and attributes.get("rel") == "stylesheet":
            self.styles.append(attributes)

    def handle_endtag(self, tag):
        if self._depth:
            self._depth -= 1

    def handle_data(self, data):
        if self._depth and data.strip():
            self.mount_content.append(data)


def _served(module: str, name: str) -> httpx.Response:
    # Sync Playwright keeps a session event loop on the calling thread. Give
    # these in-process ASGI reads their own loop; never enter a bot lifespan.
    async def read():
        app = importlib.import_module(f"ugc_bot.{module}").app
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get(f"/miniapp/{name}")

    with ThreadPoolExecutor(max_workers=1) as worker:
        return worker.submit(lambda: asyncio.run(read())).result(timeout=10)


@pytest.mark.parametrize("module,_template", HOSTS)
@pytest.mark.parametrize("asset", ASSETS)
def test_actual_webhook_mount_serves_payout_asset_bytes(
    module: str, _template: str, asset: str
) -> None:
    response = _served(module, asset)
    assert response.status_code == 200, asset
    assert response.content == (MINIAPP / asset).read_bytes()


@pytest.mark.parametrize("module,template", HOSTS)
def test_actual_template_loads_ordered_helpers_and_empty_mint_mount(
    module: str, template: str
) -> None:
    response = _served(module, template)
    assert response.status_code == 200
    assert response.content == (MINIAPP / template).read_bytes()
    document = _PayoutTemplate()
    document.feed(response.text)
    script_sources = [script["src"] for script in document.scripts]
    helpers = [f"/miniapp/{asset}" for asset in ASSETS[:3]]
    for source in helpers:
        assert script_sources.count(source) == 1, source
        script = document.scripts[script_sources.index(source)]
        assert "defer" in script, source
        assert "async" not in script, source
    assert [script_sources.index(source) for source in helpers] == sorted(
        script_sources.index(source) for source in helpers
    )
    assert script_sources.index("/miniapp/umc-shell.js") < (
        script_sources.index(helpers[-1])
    )
    styles = [style["href"] for style in document.styles]
    assert styles.count("/miniapp/umc-payouts.css") == 1
    assert styles.index("/miniapp/umc-app.css") < styles.index(
        "/miniapp/umc-payouts.css"
    )
    assert len(document.mounts) == 1
    assert document.mounts[0].get("data-umc-section") == "mint"
    assert "screen" in str(document.mounts[0].get("class", "")).split()
    assert document.mount_content == []


def _run_helpers(body: str, *, without_bigint: bool = False) -> None:
    node = shutil.which("node")
    assert node, "Node is required to exercise the actual payout helper assets"
    for asset in ASSETS[:2]:
        assert (MINIAPP / asset).is_file(), f"missing payout helper: {asset}"
    bootstrap = """
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const webcrypto = require('node:crypto').webcrypto;
const bytes = new Map();
const storage = {
  getItem(key) { return bytes.has(key) ? bytes.get(key) : null; },
  setItem(key, value) { bytes.set(key, String(value)); },
  removeItem(key) { bytes.delete(key); }
};
const sandbox = {localStorage: storage, crypto: webcrypto};
sandbox.window = sandbox;
if (process.argv[2] === 'no-bigint') sandbox.BigInt = undefined;
vm.createContext(sandbox);
const assetPath = name => path.join(process.argv[1], name);
function reloadState() {
  vm.runInContext(
    fs.readFileSync(assetPath('umc-payout-state.js'), 'utf8'), sandbox
  );
}
vm.runInContext(
  fs.readFileSync(assetPath('umc-payout-money.js'), 'utf8'), sandbox
);
reloadState();
const M = sandbox.UMCPayoutMoney;
let S = sandbox.UMCPayoutState;
assert.ok(M, 'money helper must be available on window');
assert.ok(S, 'state helper must be available on window');
const plain = value => JSON.parse(JSON.stringify(value));
const partition = {
  platform: 'telegram', actor_id: '11111111-1111-4111-8111-111111111111'
};
const reserve = {
  version: 1, action: 'RequestPayout',
  operation_key: '22222222-2222-4222-8222-222222222222',
  requisites_id: '33333333-3333-4333-8333-333333333333',
  amount_minor: '9223372036854775807', currency: 'RUB'
};
const store = {
  version: 1, action: 'StorePayoutRequisites',
  operation_key: '44444444-4444-4444-8444-444444444444',
  requirements_id: '55555555-5555-4555-8555-555555555555',
  document_id: '66666666-6666-4666-8666-666666666666',
  document_hash: 'a'.repeat(64)
};
"""
    result = subprocess.run(
        [
            node,
            "-e",
            bootstrap + body,
            str(MINIAPP),
            "no-bigint" if without_bigint else "bigint",
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize(
    "typed,minor",
    [
        ("0.01", "1"),
        ("0,01", "1"),
        ("1", "100"),
        ("12.3", "1230"),
        ("12,30", "1230"),
        ("90071992547409.91", "9007199254740991"),
        ("90071992547409.92", "9007199254740992"),
        ("90071992547409.93", "9007199254740993"),
        ("92233720368547758.07", "9223372036854775807"),
    ],
)
def test_money_parse_keeps_exact_minor_units(typed: str, minor: str) -> None:
    _run_helpers(
        f"assert.equal(M.parse({json.dumps(typed)}), {json.dumps(minor)});"
    )


@pytest.mark.parametrize(
    "typed",
    [
        "0",
        "0.00",
        "-1",
        "+1",
        "1e2",
        " 1",
        "1 ",
        "01",
        ".01",
        "1.",
        "1.001",
        "1,2.3",
        "١٢.٣٤",
        "１２.３４",
        "92233720368547758.08",
        "9223372036854775807",
        "",
    ],
)
def test_money_parse_rejects_noncanonical_or_overflowing_amounts(
    typed: str,
) -> None:
    _run_helpers(f"assert.equal(M.parse({json.dumps(typed)}), null);")


def test_money_format_preserves_maximum_and_unsafe_number_boundary() -> None:
    _run_helpers(
        """
assert.equal(M.format('0'), '0,00\u00a0RUB');
assert.equal(M.format('1'), '0,01\u00a0RUB');
assert.equal(
  M.format('9007199254740991'),
  '90\u00a0071\u00a0992\u00a0547\u00a0409,91\u00a0RUB'
);
assert.equal(
  M.format('9007199254740993'),
  '90\u00a0071\u00a0992\u00a0547\u00a0409,93\u00a0RUB'
);
assert.equal(
  M.format('9223372036854775807'),
  '92\u00a0233\u00a0720\u00a0368\u00a0547\u00a0758,07\u00a0RUB'
);
for (const value of [
  '01', '-1', '1.5', '1e2', '9223372036854775808', 1, null
]) {
  assert.equal(M.format(value), null);
}
"""
    )


def test_missing_bigint_disables_parse_but_preserves_readable_money() -> None:
    _run_helpers(
        """
assert.equal(M.available(), false);
assert.equal(M.parse('0.01'), null);
assert.equal(
  M.format('9223372036854775807'),
  '92\u00a0233\u00a0720\u00a0368\u00a0547\u00a0758,07\u00a0RUB'
);
""",
        without_bigint=True,
    )


def test_unknown_reserve_survives_reload_with_partition_isolation() -> None:
    _run_helpers(
        """
assert.equal(M.available(), true);
assert.deepEqual(plain(S.read(partition)), {status: 'empty', record: null});
assert.equal(S.write(partition, reserve), true);
assert.deepEqual(plain(JSON.parse(bytes.get(S.key(partition)))), reserve);
reloadState();
S = sandbox.UMCPayoutState;
assert.deepEqual(
  plain(S.read(partition)), {status: 'pending', record: reserve}
);
for (const other of [
  {...partition, platform: 'max'},
  {...partition, actor_id: '77777777-7777-4777-8777-777777777777'}
]) {
  assert.notEqual(S.key(other), S.key(partition));
  assert.deepEqual(plain(S.read(other)), {status: 'empty', record: null});
}
assert.equal(S.write(partition, {...reserve, amount_minor: '1'}), false);
assert.deepEqual(
  plain(S.read(partition)), {status: 'pending', record: reserve}
);
"""
    )


def test_unknown_store_retains_only_document_recovery_context() -> None:
    _run_helpers(
        """
assert.equal(S.write(partition, store), true);
reloadState();
S = sandbox.UMCPayoutState;
assert.deepEqual(plain(S.read(partition)), {status: 'pending', record: store});
assert.deepEqual(plain(JSON.parse(bytes.get(S.key(partition)))), store);
assert.equal(S.write(partition, store), true);
assert.equal(S.write(partition, reserve), false);
assert.equal(S.clear(partition, store), true);
assert.deepEqual(plain(S.read(partition)), {status: 'empty', record: null});
"""
    )


def test_late_response_cannot_remove_newer_operation() -> None:
    _run_helpers(
        """
const next = {
  ...reserve, operation_key: '88888888-8888-4888-8888-888888888888'
};
assert.equal(S.write(partition, reserve), true);
assert.equal(S.clear(partition, {...reserve, amount_minor: '1'}), false);
assert.equal(S.clear(partition, reserve), true);
assert.equal(S.write(partition, next), true);
assert.equal(S.clear(partition, reserve), false);
assert.deepEqual(plain(S.read(partition)), {status: 'pending', record: next});
assert.equal(S.write(partition, reserve), false);
assert.deepEqual(plain(S.read(partition)), {status: 'pending', record: next});
"""
    )


def test_malformed_or_secret_records_are_blocked_and_preserved() -> None:
    _run_helpers(
        """
const invalid = [
  {...reserve, details: {synthetic: 'private-test-value'}},
  {...store, init_data: 'synthetic-auth'},
  {...reserve, actor_id: partition.actor_id},
  {...reserve, version: 2},
  {...reserve, version: '1'},
  {...reserve, action: 'RecordPayoutResult'},
  {...reserve, operation_key: ''},
  {...reserve, requisites_id: '00000000-0000-0000-0000-000000000000'},
  {...reserve, requisites_id: 'invalid'},
  {...reserve, amount_minor: '0'},
  {...reserve, amount_minor: '01'},
  {...reserve, amount_minor: '9223372036854775808'},
  {...reserve, amount_minor: 100},
  {...reserve, currency: 'USD'},
  {...store, requirements_id: 'invalid'},
  {...store, document_id: null},
  {...store, document_hash: 'A'.repeat(64)},
  {...store, document_hash: 'a'.repeat(63)},
  [], null, 'synthetic'
];
const key = S.key(partition);
for (const record of invalid) {
  bytes.clear();
  assert.equal(S.write(partition, record), false);
  assert.equal(bytes.size, 0);
  const original = JSON.stringify(record);
  bytes.set(key, original);
  assert.deepEqual(plain(S.read(partition)), {status: 'blocked', record: null});
  assert.equal(S.write(partition, reserve), false);
  assert.equal(S.clear(partition, reserve), false);
  assert.equal(bytes.get(key), original);
}
bytes.set(key, '{invalid-json');
assert.deepEqual(plain(S.read(partition)), {status: 'blocked', record: null});
assert.equal(S.write(partition, reserve), false);
assert.equal(bytes.get(key), '{invalid-json');
"""
    )


def test_invalid_partition_cannot_read_write_or_clear_another_actor() -> None:
    _run_helpers(
        """
assert.equal(S.write(partition, reserve), true);
const original = bytes.get(S.key(partition));
for (const bad of [
  null, {}, {...partition, platform: 'web'},
  {...partition, actor_id: 'invalid'},
  {...partition, actor_id: '00000000-0000-0000-0000-000000000000'},
  {...partition, init_data: 'synthetic-auth'}
]) {
  assert.equal(S.key(bad), null);
  assert.deepEqual(plain(S.read(bad)), {status: 'blocked', record: null});
  assert.equal(S.write(bad, reserve), false);
  assert.equal(S.clear(bad, reserve), false);
}
assert.equal(bytes.get(S.key(partition)), original);
"""
    )


def test_storage_read_write_and_remove_failures_fail_closed() -> None:
    _run_helpers(
        """
const getItem = storage.getItem;
const setItem = storage.setItem;
const removeItem = storage.removeItem;
storage.getItem = () => { throw Error('synthetic read denial'); };
assert.deepEqual(plain(S.read(partition)), {status: 'blocked', record: null});
assert.equal(S.write(partition, reserve), false);
assert.equal(S.clear(partition, reserve), false);
storage.getItem = getItem;
storage.setItem = () => { throw Error('synthetic quota denial'); };
assert.equal(S.write(partition, reserve), false);
assert.equal(bytes.size, 0);
storage.setItem = setItem;
assert.equal(S.write(partition, reserve), true);
storage.removeItem = () => { throw Error('synthetic removal denial'); };
assert.equal(S.clear(partition, reserve), false);
assert.deepEqual(
  plain(S.read(partition)), {status: 'pending', record: reserve}
);
storage.removeItem = removeItem;
Object.defineProperty(sandbox, 'localStorage', {
  get() { throw Error('synthetic storage access denial'); }
});
reloadState();
S = sandbox.UMCPayoutState;
assert.deepEqual(plain(S.read(partition)), {status: 'blocked', record: null});
assert.equal(S.write(partition, reserve), false);
"""
    )


def test_operation_keys_require_secure_randomness_and_valid_uuid() -> None:
    _run_helpers(
        """
const uuid = new RegExp(
  '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
);
const first = S.newKey();
const second = S.newKey();
assert.match(first, uuid);
assert.match(second, uuid);
assert.notEqual(first, second);
sandbox.crypto = {getRandomValues: webcrypto.getRandomValues.bind(webcrypto)};
const fallback = S.newKey();
assert.match(fallback, uuid);
assert.notEqual(first, fallback);
sandbox.crypto = undefined;
assert.equal(S.newKey(), null);
sandbox.crypto = {
  randomUUID() { throw Error('synthetic unavailable crypto'); }
};
assert.equal(S.newKey(), null);
"""
    )
