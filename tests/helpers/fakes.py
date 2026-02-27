"""Fake objects for testing handlers and services."""

from dataclasses import dataclass, field
from typing import Any

from ugc_bot.application.messenger.dto import Invoice

_MESSAGE_REGISTRY: dict[str, "FakeMessage"] = {}
_CALLBACK_REGISTRY: dict[str, "FakeCallback"] = {}


def _register_message(message: "FakeMessage") -> None:
    """Register a fake message by chat ID."""
    _MESSAGE_REGISTRY[str(message.chat.id)] = message


def _register_callback(callback: "FakeCallback") -> None:
    """Register a fake callback by callback ID."""
    _CALLBACK_REGISTRY[str(callback.id)] = callback


def clear_fake_registries() -> None:
    """Clear message/callback registries between tests if needed."""
    _MESSAGE_REGISTRY.clear()
    _CALLBACK_REGISTRY.clear()


@dataclass
class FakeMessengerClient:
    """MessengerClient stub that records calls and updates fake objects."""

    sent_text: list[dict[str, Any]] = field(default_factory=list)
    sent_photos: list[dict[str, Any]] = field(default_factory=list)
    edited_text: list[dict[str, Any]] = field(default_factory=list)
    edited_reply_markups: list[dict[str, Any]] = field(default_factory=list)
    answered_callbacks: list[dict[str, Any]] = field(default_factory=list)
    sent_invoices: list[dict[str, Any]] = field(default_factory=list)

    async def send_text(
        self,
        *,
        chat_id: str,
        text: str,
        keyboard: object | None = None,
        parse_mode: str | None = None,
        disable_preview: bool | None = None,
    ) -> None:
        """Record send_text calls and append to message answers."""
        self.sent_text.append(
            {
                "chat_id": chat_id,
                "text": text,
                "keyboard": keyboard,
                "parse_mode": parse_mode,
                "disable_preview": disable_preview,
            }
        )
        msg = _MESSAGE_REGISTRY.get(str(chat_id))
        if msg is not None:
            if keyboard is not None:
                msg.answers.append((text, keyboard))
                msg.reply_markups.append(keyboard)
            else:
                msg.answers.append(text)

    async def send_photo(
        self,
        *,
        chat_id: str,
        file_id: str,
        caption: str | None = None,
        keyboard: object | None = None,
        parse_mode: str | None = None,
    ) -> None:
        """Record send_photo calls and append to message answers."""
        self.sent_photos.append(
            {
                "chat_id": chat_id,
                "file_id": file_id,
                "caption": caption,
                "keyboard": keyboard,
                "parse_mode": parse_mode,
            }
        )
        msg = _MESSAGE_REGISTRY.get(str(chat_id))
        if msg is not None and caption is not None:
            if keyboard is not None:
                msg.answers.append((caption, keyboard))
                msg.reply_markups.append(keyboard)
            else:
                msg.answers.append(caption)

    async def edit_text(
        self,
        *,
        chat_id: str,
        message_id: str,
        text: str,
        keyboard: object | None = None,
        parse_mode: str | None = None,
    ) -> None:
        """Record edit_text calls and append to message answers."""
        self.edited_text.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "keyboard": keyboard,
                "parse_mode": parse_mode,
            }
        )
        msg = _MESSAGE_REGISTRY.get(str(chat_id))
        if msg is not None:
            if keyboard is not None:
                msg.answers.append((text, keyboard))
                msg.reply_markups.append(keyboard)
            else:
                msg.answers.append(text)

    async def edit_reply_markup(
        self,
        *,
        chat_id: str,
        message_id: str,
        keyboard: object | None = None,
    ) -> None:
        """Record edit_reply_markup calls and append to message."""
        self.edited_reply_markups.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "keyboard": keyboard,
            }
        )
        msg = _MESSAGE_REGISTRY.get(str(chat_id))
        if msg is not None:
            msg.edit_reply_markup_calls.append(keyboard)

    async def answer_callback(
        self,
        *,
        callback_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        """Record callback answers and append to FakeCallback answers."""
        self.answered_callbacks.append(
            {
                "callback_id": callback_id,
                "text": text,
                "show_alert": show_alert,
            }
        )
        cb = _CALLBACK_REGISTRY.get(str(callback_id))
        if cb is not None and text is not None:
            cb.answers.append(text)

    async def send_invoice(self, *, chat_id: str, invoice: Invoice) -> None:
        """Record invoice send calls."""
        self.sent_invoices.append({"chat_id": chat_id, "invoice": invoice})


class FakeUser:
    """Minimal user stub for tests."""

    def __init__(
        self,
        user_id: int,
        username: str | None = None,
        first_name: str = "",
    ) -> None:
        """Initialize fake user.

        Args:
            user_id: User ID
            username: Optional username
            first_name: Optional first name
        """
        self.id = user_id
        self.username = username
        self.first_name = first_name


class FakeBot:
    """Minimal bot stub for tests."""

    def __init__(self) -> None:
        """Initialize fake bot."""
        self.invoices: list[dict] = []
        self.pre_checkout_answers: list[dict] = []
        self.messages: list[tuple[int, str]] = []

    async def send_invoice(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
        """Capture invoice calls."""
        self.invoices.append(kwargs)

    async def answer_pre_checkout_query(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
        """Capture pre-checkout query answers."""
        self.pre_checkout_answers.append(kwargs)

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: object = None,
        **kwargs: object,
    ) -> None:  # type: ignore[no-untyped-def]
        """Capture sent messages with optional reply_markup."""
        self.messages.append((chat_id, text, reply_markup))


class FakePhotoSize:
    """Minimal PhotoSize stub for message.photo."""

    def __init__(self, file_id: str = "fake_file_id") -> None:
        self.file_id = file_id


class FakeContact:
    """Minimal contact stub (e.g. shared phone via Telegram request_contact)."""

    def __init__(self, phone_number: str) -> None:
        self.phone_number = phone_number


class FakeWebAppData:
    """Minimal web_app_data stub for Mini App messages."""

    def __init__(self, data: str) -> None:
        self.data = data


class FakeMessage:
    """Minimal message stub for handler tests."""

    def __init__(
        self,
        text: str | None = None,
        user: FakeUser | None = None,
        bot: FakeBot | None = None,
        photo: list | None = None,
        caption: str | None = None,
        message_id: int = 1,
        contact: FakeContact | None = None,
        web_app_data: FakeWebAppData | None = None,
    ) -> None:
        """Initialize fake message.

        Args:
            text: Message text
            user: Optional user who sent the message
            bot: Optional bot instance
            photo: Optional list of FakePhotoSize for photo messages
            caption: Optional caption for photo messages
            contact: Optional contact (e.g. shared phone via request_contact)
            web_app_data: Optional Web App data (e.g. from Mini App sendData)
        """
        self.text = text
        self.caption = caption
        self.from_user = user
        self.bot = bot
        self.photo = photo or []
        self.message_id = message_id
        self.contact = contact
        self.web_app_data = web_app_data
        self.answers: list[str | tuple[str, object | None]] = []
        self.reply_markups: list = []
        self.reply_markup = None
        self.chat = type("Chat", (), {"id": user.id if user else 0})()
        self.successful_payment = None
        self.edit_reply_markup_calls: list[object] = []
        _register_message(self)

    async def answer(self, text: str, reply_markup=None, **kwargs) -> None:  # type: ignore[no-untyped-def]
        """Capture response text and optional reply markup."""
        if reply_markup is not None:
            self.answers.append((text, reply_markup))
            self.reply_markups.append(reply_markup)
        else:
            self.answers.append(text)

    async def edit_text(self, text: str, reply_markup=None, **kwargs) -> None:  # type: ignore[no-untyped-def]
        """Capture edited text and optional reply markup."""
        if reply_markup is not None:
            self.answers.append((text, reply_markup))
            self.reply_markups.append(reply_markup)
        else:
            self.answers.append(text)

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
        """Capture advertiser messages."""
        self.answers.append(text)

    async def edit_reply_markup(
        self, reply_markup: object = None, **kwargs: object
    ) -> None:
        """Capture edit_reply_markup calls (e.g. remove keyboard after skip)."""
        self.edit_reply_markup_calls.append(reply_markup)


class FakeCallback:
    """Minimal callback stub for tests."""

    def __init__(
        self,
        data: str,
        user: FakeUser | None,
        message: FakeMessage | None = None,
        bot: object | None = None,
        callback_id: str | None = None,
    ) -> None:
        """Initialize fake callback.

        Args:
            data: Callback data
            user: User who triggered callback (None to simulate no user)
            message: Optional message
            bot: Optional bot instance (for admin notification)
        """
        self.data = data
        self.from_user = user
        self.message = message or FakeMessage()
        self.answers: list[str] = []
        self.bot = bot
        self.id = callback_id or f"cb-{len(_CALLBACK_REGISTRY) + 1}"
        _register_callback(self)

    async def answer(
        self, text: str = "", show_alert: bool = False, **kwargs: object
    ) -> None:
        """Capture callback answer."""
        self.answers.append(text)


class FakeFSMContext:
    """Minimal FSM context for tests."""

    def __init__(self, state: str | None = None) -> None:
        """Initialize fake FSM context.

        Args:
            state: Optional initial FSM state.
        """
        self._data: dict = {}
        self.state = state
        self.cleared = False

    async def set_data(self, data: dict) -> None:  # type: ignore[no-untyped-def]
        """Replace FSM data."""
        self._data.clear()
        self._data.update(data)

    async def update_data(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        """Update FSM data."""
        self._data.update(kwargs)

    async def set_state(self, state: str | None) -> None:  # type: ignore[no-untyped-def]
        """Set FSM state."""
        self.state = state

    async def get_data(self) -> dict:  # type: ignore[no-untyped-def]
        """Get FSM data."""
        return dict(self._data)

    async def get_state(self) -> str | None:  # type: ignore[no-untyped-def]
        """Return current state."""
        return self.state

    async def clear(self) -> None:
        """Clear FSM data and state."""
        self._data.clear()
        self.state = None
        self.cleared = True


class FakeSession:
    """Minimal async session stub for tests."""

    def __init__(self) -> None:
        """Initialize fake session."""
        self.closed = False

    async def close(self) -> None:
        """Mark session as closed."""
        self.closed = True


class FakeBotWithSession(FakeBot):
    """Fake bot with session for tests that need session lifecycle."""

    def __init__(self) -> None:
        """Initialize fake bot with session."""
        super().__init__()
        self.session = FakeSession()


class FakePreCheckoutQuery:
    """Minimal pre-checkout query stub."""

    def __init__(
        self,
        query_id: str,
        bot: FakeBot | None,
        user: FakeUser | None = None,
    ) -> None:
        """Initialize fake pre-checkout query.

        Args:
            query_id: Query ID
            bot: Bot instance
            user: Optional user who initiated checkout
        """
        self.id = query_id
        self.bot = bot
        self.from_user = user or FakeUser(1)
        self.invoice_payload = "payload"


class FakeSuccessfulPayment:
    """Minimal successful payment stub."""

    def __init__(self, payload: str, charge_id: str) -> None:
        """Initialize fake successful payment.

        Args:
            payload: Invoice payload
            charge_id: Provider payment charge ID
        """
        self.invoice_payload = payload
        self.provider_payment_charge_id = charge_id
        self.total_amount = 100000
        self.currency = "RUB"


class FakeReferralService:
    """ReferralService stub for handler tests."""

    def parse_referral_code(self, text: str | None) -> str | None:
        """Return None (no referral in tests)."""
        return None

    async def save_pending_referral(self, user_id: object, code: str) -> bool:
        """No-op for tests."""
        return False
