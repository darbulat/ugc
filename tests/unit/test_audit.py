"""Tests for audit log value serialization."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from ugc_bot.domain.enums import AuditAction, PaymentStatus
from ugc_bot.infrastructure.db.audit import _serialize_value


class TestSerializeValue:
    def test_uuid(self):
        uid = uuid4()
        assert _serialize_value(uid) == str(uid)

    def test_datetime(self):
        dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert _serialize_value(dt) == "2026-01-01T12:00:00+00:00"

    def test_decimal(self):
        assert _serialize_value(Decimal("10.50")) == "10.50"

    def test_enum(self):
        assert _serialize_value(PaymentStatus.PAID) == "paid"
        assert _serialize_value(AuditAction.CREATE) == "create"

    def test_none(self):
        assert _serialize_value(None) is None

    def test_string(self):
        assert _serialize_value("hello") == "hello"

    def test_int(self):
        assert _serialize_value(42) == 42

    def test_float(self):
        assert _serialize_value(3.14) == 3.14
