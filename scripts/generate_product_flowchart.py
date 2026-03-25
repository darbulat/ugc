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
import json
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


def extract_ru_texts(
    ru_path: Path,
) -> dict[str, str]:
    """Extract {key: value} from the RU dict in ru.py using ast."""
    tree = ast.parse(ru_path.read_text())
    for node in ast.walk(tree):
        # RU uses annotated assignment: RU: dict[str, str] = {...}
        if not isinstance(node, ast.AnnAssign):
            continue
        if not (
            isinstance(node.target, ast.Name)
            and node.target.id == "RU"
            and node.value is not None
            and isinstance(node.value, ast.Dict)
        ):
            continue
        result: dict[str, str] = {}
        for k, v in zip(node.value.keys, node.value.values, strict=False):
            if (
                isinstance(k, ast.Constant)
                and isinstance(k.value, str)
                and isinstance(v, ast.Constant)
                and isinstance(v.value, str)
            ):
                result[k.value] = v.value
        return result
    return {}


def build_node_data(
    ru_texts: dict[str, str],
) -> dict[str, dict[str, str | None]]:
    """Build {node_id: {title, text, key}} from _NODE_MESSAGES."""
    result: dict[str, dict[str, str | None]] = {}
    for node_id, (kind, value) in _NODE_MESSAGES.items():
        title = _NODE_LABELS.get(node_id, node_id)
        if kind == "key":
            result[node_id] = {
                "title": title,
                "text": ru_texts.get(value, value),
                "key": value,
            }
        else:
            result[node_id] = {
                "title": title,
                "text": value,
                "key": None,
            }
    return result


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


def _resolve_message(node_id: str, ru_texts: dict[str, str]) -> str | None:
    """Resolve the bot message text for a given node."""
    entry = _NODE_MESSAGES.get(node_id)
    if entry is None:
        return None
    kind, value = entry
    if kind == "key":
        return ru_texts.get(value)
    return value


def _truncate(text: str, max_len: int = 50) -> str:
    """Truncate text for display in flowchart nodes."""
    # Remove newlines
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _make_node_label(
    base_label: str,
    node_id: str,
    ru_texts: dict[str, str],
) -> str:
    """Build a node label with bot message text included."""
    msg = _resolve_message(node_id, ru_texts)
    if not msg:
        return base_label
    short = _truncate(msg)
    # Escape quotes for Mermaid
    short = short.replace('"', "&quot;")
    return f"{base_label}<br/><i>📩 {short}</i>"


# -- Node → ru.py message mapping --

_NODE_LABELS: dict[str, str] = {
    # Entry
    "START": "/start",
    "LANG_SELECT": "Язык",
    "COUNTRY_SELECT": "Страна",
    "ROLE_SELECT": "Выбор роли",
    # Creator registration
    "CREATOR_BRANCH": "Создать профиль",
    "BR_name": "Имя",
    "BR_phone": "Телефон",
    "BR_instagram": "Instagram",
    "BR_city": "Город",
    "BR_birth_date": "Дата рождения",
    "BR_blogger_gender": "Пол",
    "BR_topics": "Тематики",
    "BR_audience_gender": "Пол аудитории",
    "BR_audience_age": "Возраст аудитории",
    "BR_audience_geo": "География аудитории",
    "BR_price": "Цена за UGC",
    "BR_barter": "Бартер",
    "BR_work_format": "Формат работы",
    "BR_agreements": "Согласие с документами",
    "VERIFY_IG": "Верификация Instagram",
    # Advertiser registration
    "ADV_BRANCH": "Начать регистрацию",
    "AR_name": "Имя",
    "AR_phone": "Телефон",
    "AR_city": "Город",
    "AR_brand": "Бренд",
    "AR_company_activity": "Деятельность компании",
    "AR_site_link": "Ссылка на сайт",
    "AR_agreements": "Согласие с документами",
    # Menus
    "CREATOR_MENU": "Меню креатора",
    "ADV_MENU": "Меню рекламодателя",
    # Order creation
    "ORDER_CREATE_START": "Создать заказ",
    "OC_order_type": "Тип заказа",
    "OC_offer_text": "Описание задачи",
    "OC_cooperation_format": "Формат сотрудничества",
    "OC_price": "Бюджет",
    "OC_barter_description": "Описание бартера",
    "OC_bloggers_needed": "Количество креаторов",
    "OC_product_link": "Ссылка на продукт",
    "OC_order_photo": "Фото продукта",
    "OC_content_usage": "Использование контента",
    "OC_deadlines": "Сроки",
    "OC_geography": "География",
    # Order lifecycle
    "ORDER_FINALIZE": "Заказ сохранён",
    "PAYMENT": "Проверка оплаты",
    "PAYMENT_INVOICE": "Счёт Telegram",
    "MODERATION": "На модерации",
    "ORDER_ACTIVE": "Заказ активен",
    # Offer responses
    "OFFER_SENT": "Офферы отправлены",
    "OFFER_RESPONSE": "Ответ блогера",
    "OFFER_ACCEPT": "Принять",
    "OFFER_SKIP": "Пропустить",
    "SKIP_REASON": "Причина отказа",
    "DESIRED_PRICE": "Желаемая цена",
    # Feedback
    "INTERACTION": "Взаимодействие",
    "FEEDBACK_START": "Запрос обратной связи",
    "FB_REASON": "Тип обратной связи",
    "FB_ISSUE": "Описание проблемы",
    "FB_NPS": "NPS-оценка",
    "FB_NPS_COMMENT": "Комментарий к оценке",
    "FB_COMPLETE": "Отзыв сохранён",
    # Complaints
    "COMPLAINT_START": "Жалоба",
    "COMPLAINT_TARGET": "Выбор блогера",
    "COMPLAINT_REASON": "Причина жалобы",
    "COMPLAINT_SAVED": "Жалоба принята",
    # Shared
    "PROFILE_VIEW": "Мой профиль",
    "MY_ORDERS": "Мои заказы",
    "EDIT_PROFILE": "Редактировать профиль",
    "EDIT_TYPE": "Выбор профиля",
    "EDIT_FIELD": "Выбор поля",
    "EDIT_VALUE": "Ввод значения",
    "SUPPORT": "Поддержка",
    # Infrastructure
    "MINIAPP": "Mini App",
    "MINIAPP_AUTH": "Авторизация Mini App",
    "MINIAPP_REG": "Регистрация в вебе",
    "MINIAPP_ORDERS": "Заказы в вебе",
    "KAFKA": "Kafka Outbox",
    "IG_STATS": "Instagram статистика",
    "SCHEDULER": "Планировщики",
    "REFERRAL": "Реферальная система",
    "ADMIN_PANEL": "Панель администратора",
}

_NODE_MESSAGES: dict[str, tuple[str, str]] = {
    # ("key", ru_key)  or  ("desc", literal description)
    # Entry
    "START": ("key", "start_message"),
    "LANG_SELECT": ("key", "language_prompt"),
    "COUNTRY_SELECT": ("key", "country_prompt"),
    "ROLE_SELECT": ("desc", "Выбор роли: Я креатор / Мне нужны UGC-креаторы"),
    # Creator registration
    "CREATOR_BRANCH": ("key", "msg_creator_intro"),
    "BR_name": ("key", "msg_step_ask_name"),
    "BR_phone": ("key", "msg_phone_request"),
    "BR_instagram": ("key", "msg_step_ask_instagram"),
    "BR_city": ("key", "msg_step_ask_city"),
    "BR_birth_date": ("key", "msg_step_ask_birth_date"),
    "BR_blogger_gender": ("key", "msg_step_ask_gender"),
    "BR_topics": ("key", "msg_step_ask_topics"),
    "BR_audience_gender": ("key", "msg_step_ask_audience_gender"),
    "BR_audience_age": ("key", "msg_step_ask_audience_age"),
    "BR_audience_geo": ("key", "msg_step_ask_audience_geo"),
    "BR_price": ("key", "msg_step_ask_price"),
    "BR_barter": ("key", "msg_step_ask_barter"),
    "BR_work_format": ("key", "msg_step_ask_work_format"),
    "BR_agreements": ("key", "msg_agreements_intro_creator"),
    "VERIFY_IG": (
        "desc",
        "Подтверждение Instagram: отправьте код в DM аккаунту UMC в Instagram",
    ),
    # Advertiser registration
    "ADV_BRANCH": ("key", "msg_advertiser_intro"),
    "AR_name": ("key", "msg_whats_your_name"),
    "AR_phone": ("key", "msg_phone_request"),
    "AR_city": ("key", "msg_what_city"),
    "AR_brand": ("key", "msg_brand_name"),
    "AR_company_activity": ("key", "msg_company_activity"),
    "AR_site_link": ("key", "msg_brand_link"),
    "AR_agreements": ("key", "msg_confirm_agreement"),
    # Menus
    "CREATOR_MENU": (
        "desc",
        "Главное меню креатора: профиль, заказы,"
        " верификация Instagram, поддержка",
    ),
    "ADV_MENU": (
        "desc",
        "Главное меню рекламодателя: создание заказа,"
        " профиль, мои заказы, поддержка",
    ),
    # Order creation
    "ORDER_CREATE_START": ("desc", "Начало создания нового заказа"),
    "OC_order_type": ("key", "msg_what_do_you_need"),
    "OC_offer_text": ("key", "msg_order_task_description"),
    "OC_cooperation_format": ("key", "msg_coop_format"),
    "OC_price": ("key", "msg_order_budget"),
    "OC_barter_description": ("key", "msg_order_barter_ask"),
    "OC_bloggers_needed": ("key", "msg_how_many_creators"),
    "OC_product_link": ("key", "msg_product_link"),
    "OC_order_photo": ("key", "msg_order_photo_intro"),
    "OC_content_usage": ("key", "msg_where_use_ugc"),
    "OC_deadlines": ("key", "msg_order_deadline"),
    "OC_geography": ("key", "msg_order_geo"),
    # Order lifecycle
    "ORDER_FINALIZE": ("key", "msg_order_created"),
    "PAYMENT": ("desc", "Система проверяет необходимость оплаты за заказ"),
    "PAYMENT_INVOICE": ("key", "msg_title_payment"),
    "MODERATION": ("key", "msg_status_pending_moderation"),
    "ORDER_ACTIVE": ("key", "msg_status_active"),
    # Offer responses
    "OFFER_SENT": ("desc", "Оффер отправлен подходящим креаторам через Kafka"),
    "OFFER_RESPONSE": ("desc", "Ожидание ответа блогера на оффер"),
    "OFFER_ACCEPT": ("key", "msg_offer_accepted"),
    "OFFER_SKIP": ("key", "msg_offer_skipped"),
    "SKIP_REASON": ("key", "msg_offer_skip_reason_prompt"),
    "DESIRED_PRICE": ("key", "msg_enter_desired_price"),
    # Feedback
    "INTERACTION": ("desc", "Период взаимодействия креатора и рекламодателя"),
    "FEEDBACK_START": (
        "desc",
        "Запрос обратной связи: удалось ли связаться с контрагентом?",
    ),
    "FB_REASON": ("desc", "Выбор типа обратной связи"),
    "FB_ISSUE": ("key", "msg_fb_issue_prompt"),
    "FB_NPS": ("desc", "NPS-оценка по шкале от 1 до 5 ⭐"),
    "FB_NPS_COMMENT": (
        "desc",
        "Комментарий к NPS-оценке: развёрнутый отзыв"
        " об опыте работы с платформой",
    ),
    "FB_COMPLETE": ("key", "msg_fb_thanks_saved"),
    # Complaints
    "COMPLAINT_START": ("desc", "Начало процесса подачи жалобы"),
    "COMPLAINT_TARGET": ("key", "msg_choose_blogger_complain"),
    "COMPLAINT_REASON": ("key", "msg_choose_complaint_reason"),
    "COMPLAINT_SAVED": ("key", "msg_fb_complaint_accepted"),
    # Shared
    "PROFILE_VIEW": ("key", "lbl_profile_your"),
    "MY_ORDERS": ("key", "msg_orders_title"),
    "EDIT_PROFILE": ("key", "msg_choose_section_edit"),
    "EDIT_TYPE": ("key", "msg_choose_profile_edit"),
    "EDIT_FIELD": (
        "desc",
        "Выбор конкретного поля для редактирования внутри раздела",
    ),
    "EDIT_VALUE": ("key", "prompt_edit_generic"),
    "SUPPORT": ("key", "support_response"),
    # Infrastructure
    "MINIAPP": ("desc", "Mini App — веб-интерфейс бота в Telegram"),
    "MINIAPP_AUTH": ("desc", "Авторизация через Telegram initData"),
    "MINIAPP_REG": ("desc", "Веб-регистрация профиля"),
    "MINIAPP_ORDERS": ("desc", "Просмотр и управление заказами в вебе"),
    "KAFKA": ("desc", "Kafka Outbox — событийная доставка офферов блогерам"),
    "IG_STATS": ("desc", "Сбор статистики Instagram через Graph API"),
    "SCHEDULER": ("desc", "Планировщики: опросы обратной связи, напоминания"),
    "REFERRAL": (
        "desc",
        "Реферальная система — начисление и выплата вознаграждений",
    ),
    "ADMIN_PANEL": ("desc", "Панель администратора (SQLAdmin)"),
}


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


def _emit_entry(lines: list[str], ru_texts: dict[str, str]) -> None:
    lines.append("    %% ENTRY POINT")
    _lbl = _make_node_label("/start", "START", ru_texts)
    lines.append(f'    START["{_lbl}"]:::entry')
    _lbl = _make_node_label("Language<br/>ru|en|be|kk|uz", "LANG_SELECT", ru_texts)
    lines.append(f'    LANG_SELECT{{"{_lbl}"}}:::country')
    _lbl = _make_node_label("Country<br/>RU|BY|KZ|UZ", "COUNTRY_SELECT", ru_texts)
    lines.append(f'    COUNTRY_SELECT{{"{_lbl}"}}:::country')
    _lbl = _make_node_label("Role Selection", "ROLE_SELECT", ru_texts)
    lines.append(f'    ROLE_SELECT{{"{_lbl}"}}:::role')
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
    ru_texts: dict[str, str],
) -> None:
    raw = states.get(group_name, [])
    ids = []
    for st in raw:
        nid = f"{prefix}_{st}"
        ids.append(nid)
        label = _state_label(context, st)
        full_label = _make_node_label(label, nid, ru_texts)
        lines.append(f'    {nid}["{full_label}"]:::regStep')
    lines.append("")
    _emit_chain(lines, ids, start_node, end_node)
    lines.append("")


def _emit_order_flow(
    lines: list[str],
    states: dict[str, list[str]],
    ru_texts: dict[str, str],
) -> None:
    lines.append("    %% ORDER CREATION")
    _lbl = _make_node_label("Create Order", "ORDER_CREATE_START", ru_texts)
    lines.append(f'    ORDER_CREATE_START["{_lbl}"]:::action')
    raw = states.get("OrderCreationStates", [])
    ids = []
    for st in raw:
        nid = f"OC_{st}"
        ids.append(nid)
        label = _state_label("order", st)
        full_label = _make_node_label(label, nid, ru_texts)
        lines.append(f'    {nid}["{full_label}"]:::orderStep')
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


def _emit_order_lifecycle(
    lines: list[str],
    ru_texts: dict[str, str],
) -> None:
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
            full_label = _make_node_label(label, nid, ru_texts)
            lines.append(f'    {nid}["{full_label}"]:::{cls}')
    _lbl = _make_node_label("Payment Required?", "PAYMENT", ru_texts)
    lines.append(f'    PAYMENT{{"{_lbl}"}}:::action')
    lines.append("")
    lines.append("    ORDER_FINALIZE --> PAYMENT")
    lines.append('    PAYMENT -->|"Yes"| PAYMENT_INVOICE')
    lines.append('    PAYMENT -->|"No (barter)"| MODERATION')
    lines.append("    PAYMENT_INVOICE --> MODERATION")
    lines.append("    MODERATION --> ORDER_ACTIVE")
    lines.append("")


def _emit_offer_responses(
    lines: list[str],
    ru_texts: dict[str, str],
) -> None:
    lines.append("    %% OFFER DISPATCH & RESPONSES")
    _n = _make_node_label
    lines.append(f'    OFFER_SENT["{_n("Offers Sent", "OFFER_SENT", ru_texts)}"]:::service')
    lines.append(f'    OFFER_RESPONSE{{"{_n("Blogger Response", "OFFER_RESPONSE", ru_texts)}"}}:::role')
    lines.append(f'    OFFER_ACCEPT["{_n("Accept", "OFFER_ACCEPT", ru_texts)}"]:::action')
    lines.append(f'    OFFER_SKIP["{_n("Skip", "OFFER_SKIP", ru_texts)}"]:::action')
    lines.append(f'    SKIP_REASON{{"{_n("Rejection Reason", "SKIP_REASON", ru_texts)}"}}:::action')
    lines.append(f'    DESIRED_PRICE["{_n("Desired Price", "DESIRED_PRICE", ru_texts)}"]:::regStep')
    lines.append("")
    lines.append("    ORDER_ACTIVE --> OFFER_SENT")
    lines.append("    OFFER_SENT --> OFFER_RESPONSE")
    lines.append('    OFFER_RESPONSE -->|"Accept"| OFFER_ACCEPT')
    lines.append('    OFFER_RESPONSE -->|"Skip"| OFFER_SKIP')
    lines.append("    OFFER_SKIP --> SKIP_REASON")
    lines.append('    SKIP_REASON -->|"Low Price"| DESIRED_PRICE')
    lines.append("")


def _emit_feedback(
    lines: list[str],
    ru_texts: dict[str, str],
) -> None:
    lines.append("    %% INTERACTION & FEEDBACK")
    _n = _make_node_label
    lines.append(f'    INTERACTION["{_n("Interaction", "INTERACTION", ru_texts)}"]:::service')
    lines.append(f'    FEEDBACK_START["{_n("Feedback Request", "FEEDBACK_START", ru_texts)}"]:::action')
    lines.append(f'    FB_REASON{{"{_n("Feedback Reason", "FB_REASON", ru_texts)}"}}:::action')
    lines.append(f'    FB_ISSUE["{_n("Describe Issue", "FB_ISSUE", ru_texts)}"]:::regStep')
    lines.append(f'    FB_NPS["{_n("NPS Score 1-5", "FB_NPS", ru_texts)}"]:::regStep')
    lines.append(f'    FB_NPS_COMMENT["{_n("NPS Comment", "FB_NPS_COMMENT", ru_texts)}"]:::regStep')
    lines.append(f'    FB_COMPLETE["{_n("Feedback Saved", "FB_COMPLETE", ru_texts)}"]:::service')
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


def _emit_complaints(
    lines: list[str],
    ru_texts: dict[str, str],
) -> None:
    lines.append("    %% COMPLAINTS")
    _n = _make_node_label
    lines.append(f'    COMPLAINT_START["{_n("Complaint", "COMPLAINT_START", ru_texts)}"]:::action')
    lines.append(f'    COMPLAINT_TARGET["{_n("Select Target", "COMPLAINT_TARGET", ru_texts)}"]:::action')
    lines.append(f'    COMPLAINT_REASON{{"{_n("Reason", "COMPLAINT_REASON", ru_texts)}"}}:::action')
    lines.append(f'    COMPLAINT_SAVED["{_n("Saved", "COMPLAINT_SAVED", ru_texts)}"]:::service')
    lines.append("")
    lines.append("    INTERACTION --> COMPLAINT_START")
    lines.append("    COMPLAINT_START --> COMPLAINT_TARGET")
    lines.append("    COMPLAINT_TARGET --> COMPLAINT_REASON")
    lines.append("    COMPLAINT_REASON --> COMPLAINT_SAVED")
    lines.append("")


def _emit_shared(
    lines: list[str],
    ru_texts: dict[str, str],
) -> None:
    lines.append("    %% SHARED FLOWS")
    _n = _make_node_label
    lines.append(f'    PROFILE_VIEW["{_n("View Profile", "PROFILE_VIEW", ru_texts)}"]:::menu')
    lines.append(f'    MY_ORDERS["{_n("My Orders", "MY_ORDERS", ru_texts)}"]:::menu')
    lines.append(f'    EDIT_PROFILE["{_n("Edit Profile", "EDIT_PROFILE", ru_texts)}"]:::action')
    lines.append(f'    EDIT_TYPE{{"{_n("Profile Type", "EDIT_TYPE", ru_texts)}"}}:::action')
    lines.append(f'    EDIT_FIELD["{_n("Select Field", "EDIT_FIELD", ru_texts)}"]:::regStep')
    lines.append(f'    EDIT_VALUE["{_n("Enter Value", "EDIT_VALUE", ru_texts)}"]:::regStep')
    lines.append(f'    SUPPORT["{_n("Support", "SUPPORT", ru_texts)}"]:::menu')
    lines.append("")
    lines.append("    EDIT_PROFILE --> EDIT_TYPE")
    lines.append("    EDIT_TYPE --> EDIT_FIELD")
    lines.append("    EDIT_FIELD --> EDIT_VALUE")
    lines.append("    EDIT_VALUE --> PROFILE_VIEW")
    lines.append("")


def _emit_infra(
    lines: list[str],
    ru_texts: dict[str, str],
) -> None:
    lines.append("    %% INFRASTRUCTURE")
    _n = _make_node_label
    lines.append(f'    MINIAPP["{_n("Mini App Web UI", "MINIAPP", ru_texts)}"]:::infra')
    lines.append(f'    MINIAPP_AUTH["{_n("Auth", "MINIAPP_AUTH", ru_texts)}"]:::infra')
    lines.append(f'    MINIAPP_REG["{_n("Web Registration", "MINIAPP_REG", ru_texts)}"]:::infra')
    lines.append(f'    MINIAPP_ORDERS["{_n("Web Orders", "MINIAPP_ORDERS", ru_texts)}"]:::infra')
    lines.append(f'    KAFKA["{_n("Kafka Outbox", "KAFKA", ru_texts)}"]:::infra')
    lines.append(f'    IG_STATS["{_n("IG Stats", "IG_STATS", ru_texts)}"]:::infra')
    lines.append(f'    SCHEDULER["{_n("Schedulers", "SCHEDULER", ru_texts)}"]:::infra')
    lines.append(f'    REFERRAL["{_n("Referral System", "REFERRAL", ru_texts)}"]:::infra')
    lines.append(f'    ADMIN_PANEL["{_n("Admin Panel", "ADMIN_PANEL", ru_texts)}"]:::infra')
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
    ru_texts: dict[str, str],
) -> str:
    """Build the full Mermaid flowchart."""
    lines: list[str] = ["flowchart TB", ""]

    _emit_styles(lines)
    _emit_entry(lines, ru_texts)

    # Creator registration
    lines.append("    %% CREATOR REGISTRATION")
    _lbl = _make_node_label("Create Profile", "CREATOR_BRANCH", ru_texts)
    lines.append(f'    CREATOR_BRANCH["{_lbl}"]:::role')
    _emit_registration(
        lines,
        states,
        "BloggerRegistrationStates",
        "BR",
        "blogger",
        "CREATOR_BRANCH",
        "CREATOR_MENU",
        ru_texts,
    )

    # Creator menu
    _lbl = _make_node_label("Creator Menu", "CREATOR_MENU", ru_texts)
    lines.append(f'    CREATOR_MENU["{_lbl}"]:::menu')
    _lbl = _make_node_label("Instagram Verify", "VERIFY_IG", ru_texts)
    lines.append(f'    VERIFY_IG["{_lbl}"]:::action')
    lines.append("    CREATOR_MENU --> VERIFY_IG")
    lines.append("    CREATOR_MENU --> PROFILE_VIEW")
    lines.append("    CREATOR_MENU --> MY_ORDERS")
    lines.append("    CREATOR_MENU --> EDIT_PROFILE")
    lines.append("    CREATOR_MENU --> SUPPORT")
    lines.append("")

    # Advertiser registration
    lines.append("    %% ADVERTISER REGISTRATION")
    _lbl = _make_node_label("Start Registration", "ADV_BRANCH", ru_texts)
    lines.append(f'    ADV_BRANCH["{_lbl}"]:::role')
    _emit_registration(
        lines,
        states,
        "AdvertiserRegistrationStates",
        "AR",
        "advertiser",
        "ADV_BRANCH",
        "ADV_MENU",
        ru_texts,
    )

    # Advertiser menu
    _lbl = _make_node_label("Advertiser Menu", "ADV_MENU", ru_texts)
    lines.append(f'    ADV_MENU["{_lbl}"]:::menu')
    lines.append("    ADV_MENU --> ORDER_CREATE_START")
    lines.append("    ADV_MENU --> PROFILE_VIEW")
    lines.append("    ADV_MENU --> MY_ORDERS")
    lines.append("    ADV_MENU --> EDIT_PROFILE")
    lines.append("    ADV_MENU --> SUPPORT")
    lines.append("")

    _emit_order_flow(lines, states, ru_texts)
    _emit_order_lifecycle(lines, ru_texts)
    _emit_offer_responses(lines, ru_texts)
    _emit_feedback(lines, ru_texts)
    _emit_complaints(lines, ru_texts)
    _emit_shared(lines, ru_texts)
    _emit_infra(lines, ru_texts)

    lines.append("    %% CLICK HANDLERS")
    for node_id in _NODE_MESSAGES:
        lines.append(f"    click {node_id} showNodeInfo")
    lines.append("")

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
#drawer-overlay {
  display:none; position:fixed; inset:0;
  background:rgba(0,0,0,0.3); z-index:100;
}
#drawer-overlay.open { display:block }
#drawer {
  position:fixed; bottom:0; left:0; right:0;
  background:#fff; border-radius:16px 16px 0 0;
  padding:20px 24px 32px;
  box-shadow:0 -4px 24px rgba(0,0,0,0.15);
  z-index:101; transform:translateY(100%);
  transition:transform 0.25s ease;
  max-height:45vh; overflow-y:auto;
}
#drawer.open { transform:translateY(0) }
#drawer-handle {
  width:40px; height:4px; background:#dee2e6;
  border-radius:2px; margin:0 auto 16px; cursor:pointer;
}
#drawer-key {
  font-size:.75rem; color:#868e96;
  font-family:monospace; margin-bottom:4px;
}
#drawer-title {
  font-size:1rem; font-weight:700;
  color:#212529; margin-bottom:8px;
}
#drawer-text {
  font-size:.9rem; color:#495057;
  line-height:1.6; white-space:pre-wrap;
}
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
<script>const NODE_DATA = NODE_DATA_PLACEHOLDER;</script>
<script src=\
"https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"\
></script>
<script>
mermaid.initialize({
  startOnLoad: true,
  theme: 'default',
  flowchart: { curve:'basis', useMaxWidth:false },
  securityLevel: 'loose'
});
document.getElementById('ts').textContent =
  'Generated: ' + new Date().toLocaleString();
</script>
<script>
function showNodeInfo(nodeId) {
  var node = NODE_DATA[nodeId];
  if (!node) return;
  document.getElementById('drawer-key').textContent = node.key || '';
  document.getElementById('drawer-title').textContent = node.title;
  document.getElementById('drawer-text').textContent = node.text;
  document.getElementById('drawer').classList.add('open');
  document.getElementById('drawer-overlay').classList.add('open');
}
function closeDrawer() {
  document.getElementById('drawer').classList.remove('open');
  document.getElementById('drawer-overlay').classList.remove('open');
}
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') closeDrawer();
});
</script>
<div id="drawer-overlay" onclick="closeDrawer()"></div>
<div id="drawer">
  <div id="drawer-handle" onclick="closeDrawer()"></div>
  <div id="drawer-key"></div>
  <div id="drawer-title"></div>
  <div id="drawer-text"></div>
</div>
</body>
</html>
"""


def build_html(
    mermaid_code: str,
    node_data: dict[str, dict[str, str | None]],
) -> str:
    """Build self-contained HTML viewer."""
    json_data = json.dumps(node_data, ensure_ascii=False)
    return (
        _HTML_TEMPLATE.replace("MERMAID_PLACEHOLDER", mermaid_code).replace(
            "NODE_DATA_PLACEHOLDER", json_data
        )
    )


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
    ru_path = (
        ROOT / "src" / "ugc_bot" / "bot" / "texts" / "defaults" / "ru.py"
    )
    ru_texts = extract_ru_texts(ru_path)
    node_data = build_node_data(ru_texts)

    mermaid = build_mermaid(states, ru_texts)
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
    html_path.write_text(build_html(mermaid, node_data))

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
