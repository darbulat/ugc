"""Localized proof, original deadlines and an explicit native MiniApp action."""

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_COPY = {
    "ru": (
        "По сотрудничеству заявлен успех. Есть возражения?",
        "Возражение с причиной возможно до",
        "Доказательство",
        "Проверьте статус сотрудничества.",
        "Первое заявление об успехе возможно до",
        "Согласованные условия",
    ),
    "en": (
        "Success has been claimed for this collaboration. Any objection?",
        "The deadline for an objection with a reason is",
        "Evidence",
        "Review the collaboration status.",
        "The deadline for the first success claim is",
        "Agreed terms",
    ),
    "kk": (
        "Ынтымақтастықтың сәтті аяқталғаны туралы мәлімделді. "
        "Қарсылығыңыз бар ма?",
        "Себебі көрсетілген қарсылықтың соңғы мерзімі",
        "Дәлел",
        "Ынтымақтастық мәртебесін тексеріңіз.",
        "Сәтті аяқталу туралы алғашқы мәлімдеменің соңғы мерзімі",
        "Келісілген шарттар",
    ),
    "be": (
        "Заяўлена аб паспяховым супрацоўніцтве. Ёсць пярэчанні?",
        "Тэрмін пярэчання з прычынай",
        "Доказ",
        "Праверце статус супрацоўніцтва.",
        "Тэрмін першай заявы аб поспеху",
        "Узгодненыя ўмовы",
    ),
    "uz": (
        "Hamkorlik muvaffaqiyatli yakunlangani bildirildi. E’tirozingiz bormi?",
        "Sababli e’tiroz bildirish muddati",
        "Dalil",
        "Hamkorlik holatini tekshiring.",
        "Muvaffaqiyat haqida birinchi bildirish muddati",
        "Kelishilgan shartlar",
    ),
}

_ACTION_LABEL = {
    "ru": "Открыть сотрудничество",
    "en": "Open collaboration",
    "kk": "Ынтымақтастықты ашу",
    "be": "Адкрыць супрацоўніцтва",
    "uz": "Hamkorlikni ochish",
}


@dataclass(frozen=True, slots=True)
class RenderedNotice:
    text: str
    deadline: datetime
    action_url: str
    action_label: str


def notice_message(origin, locale, miniapp_url):
    """Return the complete proof or fail; never silently cut an evidence URL."""
    url = urlsplit(miniapp_url)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
    ):
        raise ValueError("notice_miniapp_url_unavailable")
    work = origin.source.result.collaboration
    objection = origin.notice.purpose == "objection"
    deadline = (
        work.objection_deadline if objection else work.first_claim_deadline
    )
    words = _COPY.get(locale, _COPY["ru"])
    query = [
        (key, value)
        for key, value in parse_qsl(url.query)
        if key not in ("assignment", "assignment_id")
    ]
    query.append(("assignment", str(origin.notice.assignment_id)))
    link = urlunsplit((url.scheme, url.netloc, url.path, urlencode(query), ""))
    proof = work.evidence if objection else origin.source.result.terms_reference
    lines = (
        words[0 if objection else 3],
        str(origin.notice.assignment_id),
        f"{words[1 if objection else 4]}: {deadline.isoformat()} (UTC)",
        f"{words[2 if objection else 5]}: {proof}",
        f"Mini App: {link}",
    )
    text = "\n\n".join(lines)
    if len(text.encode("utf-16-le")) // 2 > 4000:
        raise ValueError("notice_text_exceeds_provider_limit")
    return RenderedNotice(
        text, deadline, link, _ACTION_LABEL.get(locale, _ACTION_LABEL["ru"])
    )
