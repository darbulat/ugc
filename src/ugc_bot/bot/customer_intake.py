"""Shared Telegram/MAX completion of a saved, server-priced customer brief."""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.bot.telegram.handlers.order_creation_states import (
    OrderCreationStates,
)
from ugc_bot.bot.texts.defaults.customer import customer_text
from ugc_bot.domain.enums import OrderType
from ugc_bot.domain.order_display import public_order_number
from ugc_bot.domain.order_intake import OrderIntakeCommand
from ugc_bot.domain.order_targeting import OrderTargeting
from ugc_bot.domain.social import SocialPlatform

IMAGE_REQUIREMENTS = "JPEG, 1080 × 1080 px, до 5 МБ (5 000 000 байт)"
logger = logging.getLogger(__name__)
UNAVAILABLE = (
    "Оформление сейчас недоступно. Обратитесь в поддержку через «Помощь». "
    "Бриф сохранён; вы можете повторить действие."
)


def _minor_as_decimal(value: int) -> Decimal:
    whole, cents = divmod(value, 100)
    return Decimal(f"{whole}.{cents:02d}")


def principal_for(incoming, user_id):
    return AuthenticatedMessengerPrincipal(
        user_id, incoming.user.messenger_type.value, incoming.user.external_id
    )


async def record_activity(incoming, user_id, service, event, order_id=None):
    if service is not None:
        try:
            await service.record_activity(
                user_id,
                event,
                order_id,
                principal=principal_for(incoming, user_id),
            )
        except Exception as exc:
            # Reminders are auxiliary; a transient failure must not block the
            # brief or conceal an order that has already been saved.
            logger.warning(
                "Customer activity unavailable",
                extra={
                    "platform": incoming.user.messenger_type.value,
                    "error_type": type(exc).__name__,
                },
            )


async def ask_platforms(incoming, state, messenger, intake):
    data = await state.get_data()
    user_id = UUID(str(data["user_id"]))
    try:
        eligible = await intake.eligible_policies(
            user_id, principal=principal_for(incoming, user_id)
        )
    except (ValueError, PermissionError, LookupError):
        await messenger.send_text(
            chat_id=incoming.chat_id,
            text=customer_text(
                data.get("locale", "ru"), "customer_unavailable"
            ),
        )
        return
    if eligible.writes_paused or not eligible.policies:
        await messenger.send_text(
            chat_id=incoming.chat_id,
            text=customer_text(
                data.get("locale", "ru"), "customer_unavailable"
            ),
        )
        return
    policy = max(eligible.policies, key=lambda item: item.effective_from)
    # Snapshot all command inputs before creation. Network retries reuse them.
    await state.update_data(
        intake_policy=policy.version,
        intake_selection_minor=policy.selection_minor,
        intake_accompaniment_minor=policy.accompaniment_minor,
        intake_operation_key=data.get("intake_operation_key") or str(uuid4()),
        intake_due_at=data.get("intake_due_at")
        or (datetime.now(UTC) + timedelta(days=7)).isoformat(),
    )
    await messenger.send_text(
        chat_id=incoming.chat_id,
        text=customer_text(data.get("locale", "ru"), "customer_platforms"),
    )
    await state.set_state(OrderCreationStates.platforms.state)


async def choose_platforms(incoming, state, messenger, intake):
    data = await state.get_data()
    raw = (incoming.text or "").lower().replace(" ", "")
    try:
        platforms = tuple(
            sorted({SocialPlatform(p).value for p in raw.split(",")})
        )
    except ValueError:
        await messenger.send_text(
            chat_id=incoming.chat_id,
            text=customer_text(data.get("locale", "ru"), "customer_platforms"),
        )
        return
    await state.update_data(platforms=list(platforms))
    data = await state.get_data()
    count = data["bloggers_needed"]
    selection = _minor_as_decimal(data["intake_selection_minor"] * count)
    unit = _minor_as_decimal(data["intake_accompaniment_minor"])
    await messenger.send_text(
        chat_id=incoming.chat_id,
        text=customer_text(
            data.get("locale", "ru"),
            "customer_accompaniment",
            count=count,
            selection=selection,
            unit=unit,
        )
        + "\n"
        + customer_text(data.get("locale", "ru"), "customer_payment_together"),
    )
    await state.set_state(OrderCreationStates.accompaniment.state)


def command_from_state(data, incoming):
    count = data["bloggers_needed"]
    accompanied = data["accompaniment_count"]
    return OrderIntakeCommand(
        client_id=UUID(str(data["user_id"])),
        operation_key=data["intake_operation_key"],
        policy_version=data["intake_policy"],
        product_link=data["product_link"],
        offer_text=data["offer_text"],
        honorarium=Decimal(str(data.get("price", 0))),
        selection_due_at=datetime.fromisoformat(data["intake_due_at"]),
        contact_reference=f"{incoming.user.messenger_type.value}:{incoming.user.external_id}",
        service_mode="with_manager" if accompanied else "self_service",
        accompaniment_ordinals=frozenset(range(1, accompanied + 1)),
        position_count=count,
        order_type=OrderType(data["order_type"]),
        barter_description=data.get("barter_description"),
        targeting=OrderTargeting(
            city=data.get("geography"),
            platforms=tuple(data.get("platforms", ())),
            content_usage=data.get("content_usage"),
            deadlines=data.get("deadlines"),
        ),
        image_token=UUID(data["image_token"])
        if data.get("image_token")
        else None,
    )


async def complete_intake(incoming, state, messenger, intake, followup=None):
    data = await state.get_data()
    if "accompaniment_count" not in data:
        try:
            count = int(incoming.text or "")
            if not 0 <= count <= data["bloggers_needed"]:
                raise ValueError("count")
        except ValueError:
            await messenger.send_text(
                chat_id=incoming.chat_id,
                text=customer_text(
                    data.get("locale", "ru"),
                    "customer_count",
                    count=data["bloggers_needed"],
                ),
            )
            return None
        await state.update_data(accompaniment_count=count)
        data = await state.get_data()
    try:
        command = command_from_state(data, incoming)
        result = await intake.create(
            command, principal=principal_for(incoming, command.client_id)
        )
    except (ValueError, PermissionError, LookupError):
        await messenger.send_text(
            chat_id=incoming.chat_id,
            text=customer_text(
                data.get("locale", "ru"), "customer_unavailable"
            ),
        )
        return None
    await state.update_data(saved_order_id=str(result.order_id))
    await record_activity(
        incoming, command.client_id, followup, "order_created", result.order_id
    )
    await messenger.send_text(
        chat_id=incoming.chat_id,
        text=customer_text(
            data.get("locale", "ru"),
            "customer_receipt",
            number=public_order_number(result.order_id),
            title=command.offer_text[:80],
            count=command.position_count,
            selection=_minor_as_decimal(result.selection_base_minor),
            accompanied=data["accompaniment_count"],
            accompaniment=_minor_as_decimal(
                result.total_minor - result.selection_base_minor
            ),
            total=_minor_as_decimal(result.total_minor),
        )
        + (
            "\n"
            + customer_text(
                data.get("locale", "ru"), "customer_payment_together"
            )
            if data["accompaniment_count"]
            else ""
        ),
    )
    return result


async def upload_telegram_image(message, incoming, state, messenger, images):
    data = await state.get_data()
    document = getattr(message, "document", None)
    photos = getattr(message, "photo", None)
    media = document or (photos[-1] if photos else None)
    if media is None:
        return False
    try:
        if images is None:
            raise ValueError("image_upload_unavailable")
        if getattr(media, "file_size", 0) and media.file_size > 5_000_000:
            raise ValueError("image_too_large")
        buffer = await message.bot.download(media.file_id)
        if buffer is None:
            raise ValueError("image_invalid")
        data = await state.get_data()
        user_id = UUID(str(data["user_id"]))
        image = await images.upload(
            user_id, buffer.read(), principal=principal_for(incoming, user_id)
        )
    except (ValueError, PermissionError, LookupError) as exc:
        reason = (
            str(exc)
            if str(exc)
            in {
                "image_too_large",
                "image_jpeg_required",
                "image_dimensions",
                "image_invalid",
            }
            else "image_upload_unavailable"
        )
        await messenger.send_text(
            chat_id=incoming.chat_id,
            text=customer_text(data.get("locale", "ru"), reason)
            + " "
            + customer_text(data.get("locale", "ru"), "customer_image_hint"),
        )
        return False
    await state.update_data(
        image_token=str(image.token), product_photo_file_id=None
    )
    return True
