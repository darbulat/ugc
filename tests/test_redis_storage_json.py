"""Tests for Redis storage JSON serialization."""

import json
from datetime import datetime, timezone
from uuid import uuid4

from ugc_bot.app import _json_dumps, _json_loads


def test_json_dumps_with_uuid() -> None:
    """Test JSON dumps with UUID objects."""
    user_id = uuid4()
    data = {"user_id": user_id, "name": "test"}

    result = _json_dumps(data)
    parsed = json.loads(result)

    assert parsed["user_id"] == str(user_id)
    assert parsed["name"] == "test"


def test_json_dumps_with_datetime() -> None:
    """Test JSON dumps with datetime objects."""
    now = datetime.now(timezone.utc)
    data = {"timestamp": now, "value": 123}

    result = _json_dumps(data)
    parsed = json.loads(result)

    assert parsed["timestamp"] == now.isoformat()
    assert parsed["value"] == 123


def test_json_dumps_with_mixed_types() -> None:
    """Test JSON dumps with mixed UUID, datetime, and regular types."""
    user_id = uuid4()
    order_id = uuid4()
    now = datetime.now(timezone.utc)
    data = {
        "user_id": user_id,
        "order_id": order_id,
        "created_at": now,
        "price": 15000.0,
        "is_new": True,
    }

    result = _json_dumps(data)
    parsed = json.loads(result)

    assert parsed["user_id"] == str(user_id)
    assert parsed["order_id"] == str(order_id)
    assert parsed["created_at"] == now.isoformat()
    assert parsed["price"] == 15000.0
    assert parsed["is_new"] is True


def test_json_loads() -> None:
    """Test JSON loads function."""
    data = {"user_id": "550e8400-e29b-41d4-a716-446655440000", "value": 123}
    json_str = json.dumps(data)

    result = _json_loads(json_str)

    assert result == data


def test_json_roundtrip() -> None:
    """Test roundtrip serialization/deserialization."""
    user_id = uuid4()
    order_id = uuid4()
    now = datetime.now(timezone.utc)
    original_data = {
        "user_id": user_id,
        "order_id": order_id,
        "created_at": now,
        "price": 15000.0,
        "is_new": True,
    }

    # Serialize
    json_str = _json_dumps(original_data)

    # Deserialize
    deserialized = _json_loads(json_str)

    # Check that UUIDs are strings
    assert isinstance(deserialized["user_id"], str)
    assert isinstance(deserialized["order_id"], str)
    assert deserialized["user_id"] == str(user_id)
    assert deserialized["order_id"] == str(order_id)
    assert deserialized["created_at"] == now.isoformat()
    assert deserialized["price"] == 15000.0
    assert deserialized["is_new"] is True
