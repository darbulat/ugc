#!/usr/bin/env python3
"""Generate a Mermaid flowchart of all UGC bot product flows.

Run:
    python scripts/generate_product_flowchart.py

Outputs:
    docs/product_flowchart.md  — Mermaid diagram
    docs/product_flowchart.html — self-contained HTML viewer

Re-run after changing handlers/states/keyboards to update.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOT_DIR = ROOT / "src" / "ugc_bot" / "bot"
HANDLERS_DIR = BOT_DIR / "handlers"
SERVICES_DIR = ROOT / "src" / "ugc_bot" / "application" / "services"
DOMAIN_DIR = ROOT / "src" / "ugc_bot" / "domain"
DOCS_DIR = ROOT / "docs"


def _extract_states_from_class(
    node: ast.ClassDef,
) -> list[str]:
    """Extract state names from a StatesGroup class."""
    states: list[str] = []
    for item in node.body:
        if isinstance(item, ast.Assign):
            for t in item.targets:
                if isinstance(t, ast.Name):
                    states.append(t.id)
        elif isinstance(item, ast.AnnAssign) and isinstance(
            item.target, ast.Name
        ):
            states.append(item.target.id)
    return states


def extract_states_groups(
    handlers_dir: Path,
) -> dict[str, list[str]]:
    """Return {GroupName: [state1, ...]} from handler files."""
    groups: dict[str, list[str]] = {}
    for py in sorted(handlers_dir.glob("*.py")):
        try:
            tree = ast.parse(py.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = [
                getattr(b, "attr", getattr(b, "id", "")) for b in node.bases
            ]
            if "StatesGroup" in bases:
                groups[node.name] = _extract_states_from_class(node)
    return groups


def extract_callbacks(
    keyboards_path: Path,
) -> dict[str, str]:
    """Return {CONSTANT_NAME: 'callback_data_value'}."""
    callbacks: dict[str, str] = {}
    if not keyboards_path.exists():
        return callbacks
    tree = ast.parse(keyboards_path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if (
                    isinstance(t, ast.Name)
                    and t.id.startswith("CALLBACK_")
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    callbacks[t.id] = node.value.value
    return callbacks


def extract_service_names(
    services_dir: Path,
) -> list[str]:
    """Extract service class names."""
    names: list[str] = []
    for py in sorted(services_dir.glob("*.py")):
        if py.name == "__init__.py":
            continue
        try:
            tree = ast.parse(py.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name.endswith("Service"):
                names.append(node.name)
    return names


def _get_enum_bases(node: ast.ClassDef) -> list[str]:
    return [getattr(b, "id", getattr(b, "attr", "")) for b in node.bases]


def extract_enums(
    domain_dir: Path,
) -> dict[str, list[str]]:
    """Extract StrEnum classes and their members."""
    enums: dict[str, list[str]] = {}
    enums_path = domain_dir / "enums.py"
    if not enums_path.exists():
        return enums
    tree = ast.parse(enums_path.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if "StrEnum" not in _get_enum_bases(node):
            continue
        members = []
        for item in node.body:
            if isinstance(item, ast.Assign):
                for t in item.targets:
                    if isinstance(t, ast.Name) and t.id.isupper():
                        members.append(t.id)
        enums[node.name] = members
    return enums


def count_handlers(
    handlers_dir: Path,
) -> dict[str, int]:
    """Count async handler functions per file."""
    counts: dict[str, int] = {}
    for py in sorted(handlers_dir.glob("*.py")):
        if py.name.startswith("__"):
            continue
        try:
            tree = ast.parse(py.read_text())
        except SyntaxError:
            continue
        n = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef)
        )
        if n > 0:
            counts[py.stem] = n
    return counts


# -- State labels --

_BLOGGER_LABELS: dict[str, str] = {
    "name": "Name",
    "phone": "Phone",
    "instagram": "Instagram URL",
    "city": "City + Region",
    "birth_date": "Birth Date",
    "blogger_gender": "Gender (M/F)",
    "topics": "Topics",
    "audience_gender": "Audience Gender",
    "audience_age": "Audience Age Range",
    "audience_geo": "Audience Geography",
    "price": "Price per UGC",
    "barter": "Barter? (Y/N)",
    "work_format": "Work Format (UGC/Ads)",
    "agreements": "Agreement Confirmation",
}

_ADV_LABELS: dict[str, str] = {
    "name": "Name",
    "phone": "Phone",
    "city": "City",
    "brand": "Brand Name",
    "company_activity": "Company Activity",
    "site_link": "Website URL",
    "agreements": "Agreement Confirmation",
}

_ORDER_LABELS: dict[str, str] = {
    "order_type": "Order Type",
    "offer_text": "Order Description",
    "cooperation_format": "Cooperation Format",
    "price": "Price",
    "barter_description": "Barter Description",
    "bloggers_needed": "Bloggers Needed",
    "product_link": "Product Link",
    "order_photo": "Order Photo",
    "content_usage": "Content Usage",
    "deadlines": "Deadlines",
    "geography": "Creator Geography",
}

_ALL_LABELS: dict[str, dict[str, str]] = {
    "blogger": _BLOGGER_LABELS,
    "advertiser": _ADV_LABELS,
    "order": _ORDER_LABELS,
}


def _state_label(context: str, state: str) -> str:
    return _ALL_LABELS.get(context, {}).get(state, state)


# -- Mermaid builder helpers --


def _emit_chain(
    lines: list[str],
    ids: list[str],
    start_node: str,
    end_node: str,
) -> None:
    """Emit a linear chain of nodes."""
    if not ids:
        return
    lines.append(f"    {start_node} --> {ids[0]}")
    for a, b in zip(ids, ids[1:], strict=False):
        lines.append(f"    {a} --> {b}")
    lines.append(f"    {ids[-1]} --> {end_node}")


def _emit_styles(lines: list[str]) -> None:
    lines.append("    %% Styles")
    defs = [
        ("entry", "#4CAF50", "#388E3C", "#fff"),
        ("role", "#2196F3", "#1565C0", "#fff"),
        ("regStep", "#FFF9C4", "#F9A825", "#333"),
        ("orderStep", "#E1BEE7", "#8E24AA", "#333"),
        ("action", "#FFCCBC", "#E64A19", "#333"),
        ("menu", "#B2DFDB", "#00695C", "#333"),
        ("service", "#CFD8DC", "#455A64", "#333"),
        ("infra", "#D7CCC8", "#5D4037", "#333"),
        ("country", "#C8E6C9", "#2E7D32", "#333"),
    ]
    for name, fill, stroke, color in defs:
        s = f"    classDef {name} "
        s += f"fill:{fill},stroke:{stroke},color:{color}"
        if name == "entry":
            s += ",font-weight:bold"
        lines.append(s)
    lines.append("")


def _emit_entry(lines: list[str]) -> None:
    lines.append("    %% ENTRY POINT")
    lines.append('    START["/start"]:::entry')
    lines.append('    LANG_SELECT{"Language<br/>ru|en|be|kk|uz"}:::country')
    lines.append('    COUNTRY_SELECT{"Country<br/>RU|BY|KZ|UZ"}:::country')
    lines.append('    ROLE_SELECT{"Role Selection"}:::role')
    lines.append("")
    lines.append("    START --> LANG_SELECT")
    lines.append("    LANG_SELECT --> COUNTRY_SELECT")
    lines.append("    COUNTRY_SELECT --> ROLE_SELECT")
    lines.append("")
    lines.append('    ROLE_SELECT -->|"Creator"| CREATOR_BRANCH')
    lines.append('    ROLE_SELECT -->|"Advertiser"| ADV_BRANCH')
    lines.append("")


def _emit_registration(
    lines: list[str],
    states: dict[str, list[str]],
    group_name: str,
    prefix: str,
    context: str,
    start_node: str,
    end_node: str,
) -> None:
    raw = states.get(group_name, [])
    ids = []
    for st in raw:
        nid = f"{prefix}_{st}"
        ids.append(nid)
        label = _state_label(context, st)
        lines.append(f'    {nid}["{label}"]:::regStep')
    lines.append("")
    _emit_chain(lines, ids, start_node, end_node)
    lines.append("")


def _emit_order_flow(
    lines: list[str],
    states: dict[str, list[str]],
) -> None:
    lines.append("    %% ORDER CREATION")
    lines.append('    ORDER_CREATE_START["Create Order"]:::action')
    raw = states.get("OrderCreationStates", [])
    ids = []
    for st in raw:
        nid = f"OC_{st}"
        ids.append(nid)
        label = _state_label("order", st)
        lines.append(f'    {nid}["{label}"]:::orderStep')
    lines.append("")
    if not ids:
        return
    lines.append(f"    ORDER_CREATE_START --> {ids[0]}")
    for idx in range(len(ids) - 1):
        a, b = ids[idx], ids[idx + 1]
        next_st = raw[idx + 1]
        if next_st == "barter_description":
            lines.append(f'    {a} -->|"Barter"| {b}')
        else:
            lines.append(f"    {a} --> {b}")
    # Skip barter path
    if "OC_cooperation_format" in ids and "OC_price" in ids:
        lines.append('    OC_cooperation_format -->|"Payment only"| OC_price')
    lines.append(f"    {ids[-1]} --> ORDER_FINALIZE")
    lines.append("")


def _emit_order_lifecycle(lines: list[str]) -> None:
    lines.append("    %% ORDER LIFECYCLE")
    nodes = [
        (
            "ORDER_FINALIZE",
            "Order Saved",
            "action",
        ),
        ("PAYMENT", None, None),
        (
            "PAYMENT_INVOICE",
            "Telegram Invoice",
            "action",
        ),
        (
            "MODERATION",
            "Pending Moderation",
            "service",
        ),
        (
            "ORDER_ACTIVE",
            "Order ACTIVE",
            "service",
        ),
    ]
    for nid, label, cls in nodes:
        if label and cls:
            lines.append(f'    {nid}["{label}"]:::{cls}')
    lines.append('    PAYMENT{"Payment Required?"}:::action')
    lines.append("")
    lines.append("    ORDER_FINALIZE --> PAYMENT")
    lines.append('    PAYMENT -->|"Yes"| PAYMENT_INVOICE')
    lines.append('    PAYMENT -->|"No (barter)"| MODERATION')
    lines.append("    PAYMENT_INVOICE --> MODERATION")
    lines.append("    MODERATION --> ORDER_ACTIVE")
    lines.append("")


def _emit_offer_responses(lines: list[str]) -> None:
    lines.append("    %% OFFER DISPATCH & RESPONSES")
    lines.append('    OFFER_SENT["Offers Sent"]:::service')
    lines.append('    OFFER_RESPONSE{"Blogger Response"}:::role')
    lines.append('    OFFER_ACCEPT["Accept"]:::action')
    lines.append('    OFFER_SKIP["Skip"]:::action')
    lines.append('    SKIP_REASON{"Rejection Reason"}:::action')
    lines.append('    DESIRED_PRICE["Desired Price"]:::regStep')
    lines.append("")
    lines.append("    ORDER_ACTIVE --> OFFER_SENT")
    lines.append("    OFFER_SENT --> OFFER_RESPONSE")
    lines.append('    OFFER_RESPONSE -->|"Accept"| OFFER_ACCEPT')
    lines.append('    OFFER_RESPONSE -->|"Skip"| OFFER_SKIP')
    lines.append("    OFFER_SKIP --> SKIP_REASON")
    lines.append('    SKIP_REASON -->|"Low Price"| DESIRED_PRICE')
    lines.append("")


def _emit_feedback(lines: list[str]) -> None:
    lines.append("    %% INTERACTION & FEEDBACK")
    lines.append('    INTERACTION["Interaction"]:::service')
    lines.append('    FEEDBACK_START["Feedback Request"]:::action')
    lines.append('    FB_REASON{"Feedback Reason"}:::action')
    lines.append('    FB_ISSUE["Describe Issue"]:::regStep')
    lines.append('    FB_NPS["NPS Score 1-10"]:::regStep')
    lines.append('    FB_NPS_COMMENT["NPS Comment"]:::regStep')
    lines.append('    FB_COMPLETE["Feedback Saved"]:::service')
    lines.append("")
    lines.append("    OFFER_ACCEPT --> INTERACTION")
    lines.append("    INTERACTION --> FEEDBACK_START")
    lines.append("    FEEDBACK_START --> FB_REASON")
    lines.append('    FB_REASON -->|"Problem"| FB_ISSUE')
    lines.append('    FB_REASON -->|"Great"| FB_NPS')
    lines.append("    FB_ISSUE --> FB_NPS")
    lines.append("    FB_NPS --> FB_NPS_COMMENT")
    lines.append("    FB_NPS_COMMENT --> FB_COMPLETE")
    lines.append('    FB_NPS -->|"Score 7-10"| FB_COMPLETE')
    lines.append("")


def _emit_complaints(lines: list[str]) -> None:
    lines.append("    %% COMPLAINTS")
    lines.append('    COMPLAINT_START["Complaint"]:::action')
    lines.append('    COMPLAINT_TARGET["Select Target"]:::action')
    lines.append('    COMPLAINT_REASON{"Reason"}:::action')
    lines.append('    COMPLAINT_SAVED["Saved"]:::service')
    lines.append("")
    lines.append("    INTERACTION --> COMPLAINT_START")
    lines.append("    COMPLAINT_START --> COMPLAINT_TARGET")
    lines.append("    COMPLAINT_TARGET --> COMPLAINT_REASON")
    lines.append("    COMPLAINT_REASON --> COMPLAINT_SAVED")
    lines.append("")


def _emit_shared(lines: list[str]) -> None:
    lines.append("    %% SHARED FLOWS")
    lines.append('    PROFILE_VIEW["View Profile"]:::menu')
    lines.append('    MY_ORDERS["My Orders"]:::menu')
    lines.append('    EDIT_PROFILE["Edit Profile"]:::action')
    lines.append('    EDIT_TYPE{"Profile Type"}:::action')
    lines.append('    EDIT_FIELD["Select Field"]:::regStep')
    lines.append('    EDIT_VALUE["Enter Value"]:::regStep')
    lines.append('    SUPPORT["Support"]:::menu')
    lines.append("")
    lines.append("    EDIT_PROFILE --> EDIT_TYPE")
    lines.append("    EDIT_TYPE --> EDIT_FIELD")
    lines.append("    EDIT_FIELD --> EDIT_VALUE")
    lines.append("    EDIT_VALUE --> PROFILE_VIEW")
    lines.append("")


def _emit_infra(lines: list[str]) -> None:
    lines.append("    %% INFRASTRUCTURE")
    lines.append('    MINIAPP["Mini App Web UI"]:::infra')
    lines.append('    MINIAPP_AUTH["Auth"]:::infra')
    lines.append('    MINIAPP_REG["Web Registration"]:::infra')
    lines.append('    MINIAPP_ORDERS["Web Orders"]:::infra')
    lines.append('    KAFKA["Kafka Outbox"]:::infra')
    lines.append('    IG_STATS["IG Stats"]:::infra')
    lines.append('    SCHEDULER["Schedulers"]:::infra')
    lines.append('    REFERRAL["Referral System"]:::infra')
    lines.append('    ADMIN_PANEL["Admin Panel"]:::infra')
    lines.append("")
    lines.append("    MINIAPP --> MINIAPP_AUTH")
    lines.append("    MINIAPP_AUTH --> MINIAPP_REG")
    lines.append("    MINIAPP_AUTH --> MINIAPP_ORDERS")
    lines.append("    ORDER_ACTIVE -.-> KAFKA")
    lines.append("    KAFKA -.-> OFFER_SENT")
    lines.append("    VERIFY_IG -.-> IG_STATS")
    lines.append("    SCHEDULER -.-> IG_STATS")
    lines.append("")


def build_mermaid(
    states: dict[str, list[str]],
) -> str:
    """Build the full Mermaid flowchart."""
    lines: list[str] = ["flowchart TB", ""]

    _emit_styles(lines)
    _emit_entry(lines)

    # Creator registration
    lines.append("    %% CREATOR REGISTRATION")
    lines.append('    CREATOR_BRANCH["Create Profile"]:::role')
    _emit_registration(
        lines,
        states,
        "BloggerRegistrationStates",
        "BR",
        "blogger",
        "CREATOR_BRANCH",
        "CREATOR_MENU",
    )

    # Creator menu
    lines.append('    CREATOR_MENU["Creator Menu"]:::menu')
    lines.append('    VERIFY_IG["Instagram Verify"]:::action')
    lines.append("    CREATOR_MENU --> VERIFY_IG")
    lines.append("    CREATOR_MENU --> PROFILE_VIEW")
    lines.append("    CREATOR_MENU --> MY_ORDERS")
    lines.append("    CREATOR_MENU --> EDIT_PROFILE")
    lines.append("    CREATOR_MENU --> SUPPORT")
    lines.append("")

    # Advertiser registration
    lines.append("    %% ADVERTISER REGISTRATION")
    lines.append('    ADV_BRANCH["Start Registration"]:::role')
    _emit_registration(
        lines,
        states,
        "AdvertiserRegistrationStates",
        "AR",
        "advertiser",
        "ADV_BRANCH",
        "ADV_MENU",
    )

    # Advertiser menu
    lines.append('    ADV_MENU["Advertiser Menu"]:::menu')
    lines.append("    ADV_MENU --> ORDER_CREATE_START")
    lines.append("    ADV_MENU --> PROFILE_VIEW")
    lines.append("    ADV_MENU --> MY_ORDERS")
    lines.append("    ADV_MENU --> EDIT_PROFILE")
    lines.append("    ADV_MENU --> SUPPORT")
    lines.append("")

    _emit_order_flow(lines, states)
    _emit_order_lifecycle(lines)
    _emit_offer_responses(lines)
    _emit_feedback(lines)
    _emit_complaints(lines)
    _emit_shared(lines)
    _emit_infra(lines)

    return "\n".join(lines)


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport"
  content="width=device-width, initial-scale=1.0">
<title>UGC Bot Product Flowchart</title>
<style>
* { margin:0; padding:0; box-sizing:border-box }
body {
  font-family: -apple-system, sans-serif;
  background: #1a1a2e; color: #eee;
  min-height: 100vh;
}
header {
  background: #16213e; padding: 20px 30px;
  border-bottom: 2px solid #0f3460;
}
header h1 { font-size: 1.5rem }
.legend {
  display:flex; gap:16px; flex-wrap:wrap;
  padding:12px 30px; background:#16213e;
}
.legend span {
  display:flex; align-items:center;
  gap:6px; font-size:.8rem;
}
.dot {
  width:14px; height:14px;
  border-radius:3px; display:inline-block;
}
.diagram-container {
  padding:30px; overflow:auto;
  min-height: calc(100vh - 140px);
}
.mermaid {
  background:#fff; border-radius:12px;
  padding:30px;
}
#ts { font-size:.75rem; color:#666; padding:8px 30px }
</style>
</head>
<body>
<header><h1>UGC Bot Product Flowchart</h1></header>
<div class="legend">
  <span><span class="dot"
    style="background:#4CAF50"></span> Entry</span>
  <span><span class="dot"
    style="background:#2196F3"></span> Role</span>
  <span><span class="dot"
    style="background:#FFF9C4"></span> Registration</span>
  <span><span class="dot"
    style="background:#E1BEE7"></span> Order</span>
  <span><span class="dot"
    style="background:#FFCCBC"></span> Action</span>
  <span><span class="dot"
    style="background:#B2DFDB"></span> Menu</span>
  <span><span class="dot"
    style="background:#CFD8DC"></span> Service</span>
  <span><span class="dot"
    style="background:#D7CCC8"></span> Infra</span>
</div>
<div class="diagram-container">
<pre class="mermaid">
MERMAID_PLACEHOLDER
</pre>
</div>
<div id="ts"></div>
<script src=\
"https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"\
></script>
<script>
mermaid.initialize({{
  startOnLoad: true,
  theme: 'default',
  flowchart: {{ curve:'basis', useMaxWidth:false }},
  securityLevel: 'loose'
}});
document.getElementById('ts').textContent =
  'Generated: ' + new Date().toLocaleString();
</script>
</body>
</html>
"""


def build_html(mermaid_code: str) -> str:
    """Build self-contained HTML viewer."""
    return _HTML_TEMPLATE.replace("MERMAID_PLACEHOLDER", mermaid_code)


def build_stats_md(
    states: dict[str, list[str]],
    callbacks: dict[str, str],
    services: list[str],
    enums: dict[str, list[str]],
    handler_counts: dict[str, int],
) -> str:
    """Build markdown stats summary."""
    total_states = sum(len(v) for v in states.values())
    total_handlers = sum(handler_counts.values())
    lines = [
        "## Product Stats (auto-generated)",
        "",
        f"- **FSM State Groups:** {len(states)}",
        f"- **Total FSM States:** {total_states}",
        f"- **Callback Constants:** {len(callbacks)}",
        f"- **Services:** {len(services)}",
        f"- **Domain Enums:** {len(enums)}",
        f"- **Handler files:** {len(handler_counts)}"
        f" ({total_handlers} async handlers)",
        "",
        "### State Groups",
        "",
    ]
    for name, sts in states.items():
        joined = ", ".join(sts)
        lines.append(f"- **{name}** ({len(sts)}): {joined}")
    lines += ["", "### Services", ""]
    for s in services:
        lines.append(f"- {s}")
    lines += ["", "### Domain Enums", ""]
    for name, members in enums.items():
        joined = ", ".join(members)
        lines.append(f"- **{name}**: {joined}")
    return "\n".join(lines)


def main() -> None:
    """Generate flowchart files."""
    DOCS_DIR.mkdir(exist_ok=True)

    states = extract_states_groups(HANDLERS_DIR)
    kb_path = BOT_DIR / "handlers" / "keyboards.py"
    callbacks = extract_callbacks(kb_path)
    services = extract_service_names(SERVICES_DIR)
    enums = extract_enums(DOMAIN_DIR)
    handler_counts = count_handlers(HANDLERS_DIR)

    mermaid = build_mermaid(states)
    stats = build_stats_md(
        states,
        callbacks,
        services,
        enums,
        handler_counts,
    )

    md_path = DOCS_DIR / "product_flowchart.md"
    md_content = textwrap.dedent(f"""\
        # UGC Bot — Product Flowchart

        > Auto-generated by
        > `scripts/generate_product_flowchart.py`.
        > Re-run after changing handlers/states/keyboards.

        {stats}

        ## Flowchart

        ```mermaid
        {mermaid}
        ```
    """)
    md_path.write_text(md_content)

    html_path = DOCS_DIR / "product_flowchart.html"
    html_path.write_text(build_html(mermaid))

    total = sum(len(v) for v in states.values())
    print(f"Generated: {md_path}")  # noqa: T201
    print(f"Generated: {html_path}")  # noqa: T201
    print(  # noqa: T201
        f"\nStats: {len(states)} groups, "
        f"{total} states, "
        f"{len(callbacks)} callbacks, "
        f"{len(services)} services",
    )


if __name__ == "__main__":
    main()
