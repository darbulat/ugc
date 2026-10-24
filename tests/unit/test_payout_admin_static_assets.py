"""Verify the actual admin assets and exact shared-template integration."""

import json
import re
import subprocess
from pathlib import Path

import pytest

from tests.unit.test_payout_owner_static_assets import HOSTS, _served

MINIAPP = Path(__file__).resolve().parents[2] / "src/ugc_bot/miniapp"


@pytest.mark.parametrize("module,_template", HOSTS)
@pytest.mark.parametrize(
    "asset", ["umc-payout-admin.js", "umc-payout-admin.css"]
)
def test_admin_actual_static_bytes(module, _template, asset):
    response = _served(module, asset)
    assert response.status_code == 200
    assert response.content == (MINIAPP / asset).read_bytes()


@pytest.mark.parametrize("_module,template", HOSTS)
def test_admin_template_empty_mount_and_order(_module, template):
    source = (MINIAPP / template).read_text()
    assert source.count('id="screen-payout-admin"') == 1
    assert (
        'id="screen-payout-admin" class="screen umc-payout-admin" '
        'data-umc-section="mint" aria-busy="false"></section>' in source
    )
    assert (
        source.index('src="/miniapp/umc-shell.js"')
        < source.index('src="/miniapp/umc-payout-admin.js" defer')
        < source.index('src="/miniapp/umc-payouts.js"')
    )
    assert source.index('href="/miniapp/umc-payouts.css"') < source.index(
        'href="/miniapp/umc-payout-admin.css"'
    )


def test_admin_has_no_persistence_or_external_io_sink():
    source = (MINIAPP / "umc-payout-admin.js").read_text()
    for forbidden in (
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "console.",
        "sendBeacon",
        "clipboard",
        "window.open",
        "location.",
        "fetch(",
        "XMLHttpRequest",
        "ids.read(",
        "ids.write(",
        "ids.clear(",
        "ids.key(",
        "URLSearchParams",
        "download=",
    ):
        assert forbidden not in source, forbidden
    assert re.search(
        r"Object\.freeze\s*\(\s*\{\s*open\s*:\s*open\s*\}\s*\)", source
    )


@pytest.mark.parametrize("_module,template", HOSTS)
def test_actual_template_inline_scripts_parse(_module, template):
    source = (MINIAPP / template).read_text()
    scripts = re.findall(
        r"<script\b(?![^>]*\bsrc=)[^>]*>(.*?)</script>", source, re.S
    )
    assert len(scripts) == 2
    result = subprocess.run(
        [
            "node",
            "-e",
            "const vm=require('node:vm');let value='';"
            "process.stdin.on('data',d=>value+=d);"
            "process.stdin.on('end',()=>JSON.parse(value)"
            ".forEach(s=>new vm.Script(s)));",
        ],
        input=json.dumps(scripts),
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
