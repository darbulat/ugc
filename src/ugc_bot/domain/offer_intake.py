"""Response intake is independent of payment and work completion."""

from datetime import datetime, timedelta, timezone

from ugc_bot.domain.enums import OrderStatus

RESERVE_WINDOW = timedelta(hours=72)


def intake_open(
    status: str,
    dispatch_stopped: bool,
    reserve_until: datetime | None,
    *,
    now: datetime | None = None,
) -> bool:
    if dispatch_stopped or status not in (
        OrderStatus.ACTIVE,
        OrderStatus.CLOSED,
    ):
        return False
    if reserve_until is None:
        return status == OrderStatus.ACTIVE
    at = now or datetime.now(timezone.utc)
    return at < reserve_until.replace(
        tzinfo=reserve_until.tzinfo or timezone.utc
    )


def reserve_notice(reserve_until: datetime, locale: str = "ru") -> str:
    deadline = reserve_until.replace(
        tzinfo=reserve_until.tzinfo or timezone.utc
    ).astimezone(timezone(timedelta(hours=3)))
    stamp = deadline.strftime("%d.%m.%Y %H:%M")
    if locale.lower().split("-", 1)[0] == "ru":
        return (
            "Основной состав набран. Принимаем заявки в резерв до "
            f"{stamp} МСК. Участие не гарантировано."
        )
    return (
        "The main selection is full. Reserve applications are accepted until "
        f"{stamp} (UTC+3). Participation is not guaranteed."
    )
