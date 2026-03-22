# Flowchart Node Messages — Design Spec

**Date:** 2026-03-22
**Feature:** Click-to-show message text on product flowchart nodes
**Files affected:** `scripts/generate_product_flowchart.py`, `docs/product_flowchart.html`

---

## Overview

When a user clicks a node in the HTML product flowchart, a bottom drawer slides up showing the corresponding bot message text from `ru.py`. Infrastructure nodes with no user-facing message show a hardcoded description instead.

---

## Data Layer

### `_NODE_MESSAGES` dict

A new top-level constant in `generate_product_flowchart.py`:

```python
_NODE_MESSAGES: dict[str, tuple[str, str]] = {
    # ("key", ru_key)  or  ("desc", literal description)
    "START":              ("key",  "start_message"),
    "LANG_SELECT":        ("key",  "language_prompt"),
    "COUNTRY_SELECT":     ("key",  "country_prompt"),
    # Creator registration
    "CREATOR_BRANCH":     ("key",  "msg_creator_intro"),
    "BR_name":            ("key",  "msg_step_ask_name"),
    "BR_phone":           ("key",  "msg_phone_request"),
    "BR_instagram":       ("key",  "msg_step_ask_instagram"),
    "BR_city":            ("key",  "msg_step_ask_city"),
    "BR_birth_date":      ("key",  "msg_step_ask_birth_date"),
    "BR_blogger_gender":  ("key",  "msg_step_ask_gender"),
    "BR_topics":          ("key",  "msg_step_ask_topics"),
    "BR_audience_gender": ("key",  "msg_step_ask_audience_gender"),
    "BR_audience_age":    ("key",  "msg_step_ask_audience_age"),
    "BR_audience_geo":    ("key",  "msg_step_ask_audience_geo"),
    "BR_price":           ("key",  "msg_step_ask_price"),
    "BR_barter":          ("key",  "msg_step_ask_barter"),
    "BR_work_format":     ("key",  "msg_step_ask_work_format"),
    "BR_agreements":      ("key",  "msg_agreements_intro_creator"),
    "VERIFY_IG":          ("key",  "msg_instagram_verify_instruction"),
    # Advertiser registration
    "ADV_BRANCH":         ("key",  "msg_advertiser_intro"),
    "AR_name":            ("key",  "msg_whats_your_name"),
    "AR_phone":           ("key",  "msg_phone_request"),
    "AR_city":            ("key",  "msg_what_city"),
    "AR_brand":           ("key",  "msg_brand_name"),
    "AR_company_activity":("key",  "msg_company_activity"),
    "AR_site_link":       ("key",  "msg_brand_link"),
    "AR_agreements":      ("key",  "msg_confirm_agreement"),
    # Order creation
    "ORDER_CREATE_START": ("desc", "Начало создания нового заказа"),
    "OC_order_type":      ("key",  "msg_what_do_you_need"),
    "OC_offer_text":      ("key",  "msg_order_task_description"),
    "OC_cooperation_format":("key","msg_coop_format"),
    "OC_price":           ("key",  "msg_order_budget"),
    "OC_barter_description":("key","msg_order_barter_ask"),
    "OC_bloggers_needed": ("key",  "msg_how_many_creators"),
    "OC_product_link":    ("key",  "msg_product_link"),
    "OC_order_photo":     ("key",  "msg_order_photo_intro"),
    "OC_content_usage":   ("key",  "msg_where_use_ugc"),
    "OC_deadlines":       ("key",  "msg_order_deadline"),
    "OC_geography":       ("key",  "msg_order_geo"),
    # Order lifecycle
    "ORDER_FINALIZE":     ("key",  "msg_order_created"),
    "PAYMENT":            ("desc", "Система проверяет необходимость оплаты за заказ"),
    "PAYMENT_INVOICE":    ("key",  "msg_title_payment"),
    "MODERATION":         ("key",  "msg_status_pending_moderation"),
    "ORDER_ACTIVE":       ("key",  "msg_status_active"),
    # Offer responses
    "OFFER_SENT":         ("desc", "Оффер отправлен подходящим креаторам через Kafka"),
    "OFFER_RESPONSE":     ("desc", "Ожидание ответа блогера на оффер"),
    "OFFER_ACCEPT":       ("key",  "msg_offer_accepted"),
    "OFFER_SKIP":         ("key",  "msg_offer_skipped"),
    "SKIP_REASON":        ("key",  "msg_offer_skip_reason_prompt"),
    "DESIRED_PRICE":      ("key",  "msg_enter_desired_price"),
    # Feedback
    "INTERACTION":        ("desc", "Период взаимодействия креатора и рекламодателя"),
    "FEEDBACK_START":     ("key",  "msg_feedback_request_adv"),
    "FB_REASON":          ("desc", "Выбор типа обратной связи"),
    "FB_ISSUE":           ("key",  "msg_fb_issue_prompt"),
    "FB_NPS":             ("key",  "msg_fb_nps_question"),
    "FB_NPS_COMMENT":     ("key",  "msg_fb_nps_prompt_5_adv"),
    "FB_COMPLETE":        ("key",  "msg_fb_thanks_saved"),
    # Complaints
    "COMPLAINT_START":    ("desc", "Начало процесса подачи жалобы"),
    "COMPLAINT_TARGET":   ("key",  "msg_choose_blogger_complain"),
    "COMPLAINT_REASON":   ("key",  "msg_choose_complaint_reason"),
    "COMPLAINT_SAVED":    ("key",  "msg_fb_complaint_accepted"),
    # Shared
    "PROFILE_VIEW":       ("key",  "lbl_profile_your"),
    "MY_ORDERS":          ("key",  "msg_orders_title"),
    "EDIT_PROFILE":       ("key",  "msg_choose_section_edit"),
    "EDIT_TYPE":          ("key",  "msg_choose_profile_edit"),
    "EDIT_FIELD":         ("key",  "msg_choose_section_edit"),
    "EDIT_VALUE":         ("key",  "prompt_edit_generic"),
    "SUPPORT":            ("key",  "support_response"),
    # Infrastructure
    "MINIAPP":            ("desc", "Mini App — веб-интерфейс бота в Telegram"),
    "MINIAPP_AUTH":       ("desc", "Авторизация через Telegram initData"),
    "MINIAPP_REG":        ("desc", "Веб-регистрация профиля"),
    "MINIAPP_ORDERS":     ("desc", "Просмотр и управление заказами в вебе"),
    "KAFKA":              ("desc", "Kafka Outbox — событийная доставка офферов блогерам"),
    "IG_STATS":           ("desc", "Сбор статистики Instagram через Graph API"),
    "SCHEDULER":          ("desc", "Планировщики: опросы обратной связи, напоминания"),
    "REFERRAL":           ("desc", "Реферальная система — начисление и выплата вознаграждений"),
    "ADMIN_PANEL":        ("desc", "Панель администратора (SQLAdmin)"),
}
```

### `extract_ru_texts(ru_path: Path) -> dict[str, str]`

Parses `ru.py` using `ast`, walks the `RU` dict literal, returns `{key: value}`. Uses the same `ast`-based approach as other extraction functions in the script. Handles multi-line string concatenation via `ast.literal_eval` on the value node.

### `build_node_data(...) -> dict[str, dict]`

Called in `main()`. For each entry in `_NODE_MESSAGES`:
- `"key"` entries: look up text from `extract_ru_texts()`, use the human-readable label from `_ALL_LABELS` (or the key itself) as `title`
- `"desc"` entries: use the literal string as `text`, derive `title` from the node label in the diagram

Returns `{node_id: {"title": str, "text": str, "key": str|None}}`.

---

## Mermaid Diagram Changes

`build_mermaid()` appends a `%% CLICK HANDLERS` section at the end:

```
    %% CLICK HANDLERS
    click START showNodeInfo
    click LANG_SELECT showNodeInfo
    ...
```

One `click <NODE_ID> showNodeInfo` line per entry in `_NODE_MESSAGES`. Requires `securityLevel: 'loose'` (already set in the HTML template).

---

## HTML Changes

### Embedded data

In `build_html()`, `NODE_DATA` is injected as a JSON constant before the closing `</script>`:

```html
<script>
const NODE_DATA = { /* json.dumps(node_data, ensure_ascii=False) */ };
</script>
```

### Drawer HTML

Added before `</body>`:

```html
<div id="drawer-overlay" onclick="closeDrawer()"></div>
<div id="drawer">
  <div id="drawer-handle" onclick="closeDrawer()"></div>
  <div id="drawer-key"></div>
  <div id="drawer-title"></div>
  <div id="drawer-text"></div>
</div>
```

### Drawer CSS

```css
#drawer-overlay {
  display: none;
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.3);
  z-index: 100;
}
#drawer-overlay.open { display: block; }

#drawer {
  position: fixed; bottom: 0; left: 0; right: 0;
  background: #fff;
  border-radius: 16px 16px 0 0;
  padding: 20px 24px 32px;
  box-shadow: 0 -4px 24px rgba(0,0,0,0.15);
  z-index: 101;
  transform: translateY(100%);
  transition: transform 0.25s ease;
  max-height: 40vh;
  overflow-y: auto;
}
#drawer.open { transform: translateY(0); }

#drawer-handle {
  width: 40px; height: 4px;
  background: #dee2e6; border-radius: 2px;
  margin: 0 auto 16px; cursor: pointer;
}
#drawer-key {
  font-size: 0.75rem; color: #868e96;
  font-family: monospace; margin-bottom: 4px;
}
#drawer-title {
  font-size: 1rem; font-weight: 700;
  color: #212529; margin-bottom: 8px;
}
#drawer-text {
  font-size: 0.9rem; color: #495057;
  line-height: 1.6; white-space: pre-wrap;
}
```

### JavaScript

```js
function showNodeInfo(nodeId) {
  const node = NODE_DATA[nodeId];
  if (!node) return;
  document.getElementById('drawer-key').textContent = node.key ?? '';
  document.getElementById('drawer-title').textContent = node.title;
  document.getElementById('drawer-text').textContent = node.text;
  document.getElementById('drawer').classList.add('open');
  document.getElementById('drawer-overlay').classList.add('open');
}

function closeDrawer() {
  document.getElementById('drawer').classList.remove('open');
  document.getElementById('drawer-overlay').classList.remove('open');
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeDrawer();
});
```

---

## Implementation Notes

- `extract_ru_texts` uses `ast.literal_eval` on the `RU` dict value node — handles string concatenation in parentheses correctly.
- `msg_step_ask_price` and `msg_order_budget` contain `{currency}` placeholder — shown as-is in the drawer (context is clear).
- `msg_orders_title` contains `{page}/{total_pages}` placeholder — shown as-is.
- Node labels for `title` field: reuse `_ALL_LABELS` where available, otherwise use the human-readable label already defined inline in `_emit_*` functions. For simplicity, `title` for "key" nodes is derived from the node's Mermaid label string (already in the emit functions).
- No new files created — all changes go into `generate_product_flowchart.py`.

---

## Out of Scope

- Showing multiple messages per node
- Live reload when `ru.py` changes
- Localization beyond `ru`
- Editing texts from the UI
