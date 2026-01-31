"""Fake objects for testing handlers and services."""


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
        self, chat_id: int, text: str, reply_markup: object = None, **kwargs: object
    ) -> None:  # type: ignore[no-untyped-def]
        """Capture sent messages."""
        self.messages.append((chat_id, text))


class FakeMessage:
    """Minimal message stub for handler tests."""

    def __init__(
        self,
        text: str | None = None,
        user: FakeUser | None = None,
        bot: FakeBot | None = None,
    ) -> None:
        """Initialize fake message.

        Args:
            text: Message text
            user: Optional user who sent the message
            bot: Optional bot instance
        """
        self.text = text
        self.from_user = user
        self.bot = bot
        self.answers: list[str | tuple[str, object | None]] = []
        self.reply_markups: list = []
        self.chat = type("Chat", (), {"id": user.id if user else 0})()
        self.successful_payment = None

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


class FakeCallback:
    """Minimal callback stub for tests."""

    def __init__(
        self,
        data: str,
        user: FakeUser,
        message: FakeMessage | None = None,
    ) -> None:
        """Initialize fake callback.

        Args:
            data: Callback data
            user: User who triggered callback
            message: Optional message
        """
        self.data = data
        self.from_user = user
        self.message = message or FakeMessage()
        self.answers: list[str] = []

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


class FakeFsmDraftService:
    """Minimal FSM draft service stub for handler tests (no draft saved/restored)."""

    async def save_draft(
        self, user_id: object, flow_type: str, state_key: str, data: object
    ) -> None:
        """No-op."""

    async def get_draft(self, user_id: object, flow_type: str) -> None:
        """Return None (no draft)."""
        return None

    async def delete_draft(self, user_id: object, flow_type: str) -> None:
        """No-op."""


class RecordingFsmDraftService(FakeFsmDraftService):
    """Fake draft service that records save_draft calls and can return a configured draft."""

    def __init__(self, draft_to_return: object = None) -> None:
        """Initialize with optional draft to return from get_draft."""
        self.save_calls: list[tuple[object, str, str, object]] = []
        self.delete_calls: list[tuple[object, str]] = []
        self._draft = draft_to_return

    async def save_draft(
        self, user_id: object, flow_type: str, state_key: str, data: object
    ) -> None:
        """Record the call."""
        self.save_calls.append((user_id, flow_type, state_key, data))

    async def get_draft(self, user_id: object, flow_type: str) -> object:
        """Return configured draft or None."""
        return self._draft

    async def delete_draft(self, user_id: object, flow_type: str) -> None:
        """Record the call."""
        self.delete_calls.append((user_id, flow_type))


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

    def __init__(self, query_id: str, bot: FakeBot) -> None:
        """Initialize fake pre-checkout query.

        Args:
            query_id: Query ID
            bot: Bot instance
        """
        self.id = query_id
        self.bot = bot


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
