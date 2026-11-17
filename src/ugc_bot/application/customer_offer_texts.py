"""Positive localized quote copy; all amounts are injected persisted values."""

from decimal import Decimal

_OFFER = {
    "ru": (
        "Начните с {count} авторов: подбор — от {total} {currency} "
        "({unit} {currency} за автора).",
        "Сохранённый подбор: {count} авторов, {total} {currency} "
        "({unit} {currency} за автора).",
        "Сопровождение менеджера — {manager} {currency} за выбранного автора.",
    ),
    "en": (
        "Start with {count} creators: selection from {total} "
        "{currency} ({unit} {currency} per creator).",
        "Your saved selection: {count} creators, {total} {currency} "
        "({unit} {currency} per creator).",
        "Manager support: {manager} {currency} per selected creator.",
    ),
    "kk": (
        "{count} автордан бастаңыз: іріктеу {total} {currency} бастап "
        "(әр авторға {unit} {currency}).",
        "Сақталған іріктеу: {count} автор, {total} {currency} (әр "
        "авторға {unit} {currency}).",
        "Менеджер сүйемелдеуі — таңдалған авторға {manager} {currency}.",
    ),
    "be": (
        "Пачніце з {count} аўтараў: падбор ад {total} {currency} "
        "({unit} {currency} за аўтара).",
        "Захаваны падбор: {count} аўтараў, {total} {currency} "
        "({unit} {currency} за аўтара).",
        "Суправаджэнне менеджара — {manager} {currency} за абранага аўтара.",
    ),
    "uz": (
        "{count} muallifdan boshlang: tanlash {total} {currency} dan "
        "(har bir muallif uchun {unit} {currency}).",
        "Saqlangan tanlov: {count} muallif, {total} {currency} (har "
        "bir muallif uchun {unit} {currency}).",
        "Menejer yordami — tanlangan muallif uchun {manager} {currency}.",
    ),
}


def offer_text(offer: dict, locale: str, *, stage: int | None = None) -> str:
    templates = _OFFER.get(locale, _OFFER["ru"])

    def money(value):
        if locale == "ru" and stage is not None:
            return (
                format(Decimal(value) / 100, ",.2f")
                .rstrip("0")
                .rstrip(".")
                .replace(",", " ")
                .replace(".", ",")
            )
        return (
            format(Decimal(value) / 100, "f").rstrip("0").rstrip(".")
            if value % 100
            else str(value // 100)
        )

    values = dict(
        count=offer["position_count"],
        currency=offer["currency"],
        total=money(offer["selection_base_minor"]),
        unit=money(offer["selection_unit_minor"]),
        manager=money(offer["accompaniment_unit_minor"])
        if offer.get("accompaniment_unit_minor")
        else "",
    )
    if locale == "ru" and stage is not None:
        values["currency"] = (
            "₽" if values["currency"] == "RUB" else values["currency"]
        )
        selection = (
            "Ваш подбор из {count} авторов — {total} {currency}"
            if offer.get("saved")
            else "Подбор {count} авторов — от {total} {currency}"
        )
        detail = "Стоимость за автора — {unit} {currency}"
        if stage == 2 and values["manager"]:
            detail = (
                "Сопровождение менеджера — {manager} {currency} "
                "за выбранного автора"
            )
        return (selection + "\n" + detail).format(**values)
    text = templates[1 if offer.get("saved") else 0].format(**values)
    if values["manager"]:
        text += "\n" + templates[2].format(**values)
    return text
