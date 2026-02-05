"""Tests for FSM draft serializer."""

from datetime import datetime, timezone
from uuid import uuid4

from ugc_bot.domain.enums import AudienceGender, WorkFormat
from ugc_bot.infrastructure.fsm_draft_serializer import (
    deserialize_fsm_data,
    serialize_fsm_data,
)


def test_serialize_fsm_data_uuid_to_str() -> None:
    """UUID values are serialized to string."""
    user_id = uuid4()
    data = {"user_id": user_id, "nickname": "alice"}
    result = serialize_fsm_data(data)
    assert result["user_id"] == str(user_id)
    assert result["nickname"] == "alice"


def test_serialize_fsm_data_enum_to_value() -> None:
    """Enum values are serialized to .value."""
    data = {
        "audience_gender": AudienceGender.ALL,
        "work_format": WorkFormat.UGC_ONLY,
    }
    result = serialize_fsm_data(data)
    assert result["audience_gender"] == "all"
    assert result["work_format"] == "ugc_only"


def test_serialize_fsm_data_nested_dict() -> None:
    """Nested dict (e.g. topics) is serialized recursively."""
    data = {"topics": {"selected": ["a", "b"]}}
    result = serialize_fsm_data(data)
    assert result["topics"] == {"selected": ["a", "b"]}


def test_deserialize_fsm_data_blogger_flow() -> None:
    """Deserialize blogger_registration: user_id -> UUID, enums restored."""
    data = {
        "user_id": str(uuid4()),
        "audience_gender": "all",
        "work_format": "ugc_only",
        "nickname": "bob",
    }
    result = deserialize_fsm_data(data, "blogger_registration")
    assert hasattr(result["user_id"], "hex")
    assert result["audience_gender"] == AudienceGender.ALL
    assert result["work_format"] == WorkFormat.UGC_ONLY
    assert result["nickname"] == "bob"


def test_deserialize_fsm_data_order_flow_uuid() -> None:
    """Deserialize order_creation: user_id -> UUID."""
    user_id = uuid4()
    data = {"user_id": str(user_id), "product_link": "https://x.com"}
    result = deserialize_fsm_data(data, "order_creation")
    assert result["user_id"] == user_id
    assert result["product_link"] == "https://x.com"


def test_deserialize_fsm_data_advertiser_flow_uuid() -> None:
    """Deserialize advertiser_registration: user_id -> UUID."""
    user_id = uuid4()
    data = {"user_id": str(user_id), "brand": "Test"}
    result = deserialize_fsm_data(data, "advertiser_registration")
    assert result["user_id"] == user_id
    assert result["brand"] == "Test"


def test_deserialize_fsm_data_edit_profile_edit_user_id() -> None:
    """Deserialize edit_profile: edit_user_id -> UUID."""
    user_id = uuid4()
    data = {"edit_user_id": str(user_id), "editing_field": "city"}
    result = deserialize_fsm_data(data, "edit_profile")
    assert result["edit_user_id"] == user_id
    assert result["editing_field"] == "city"


def test_serialize_fsm_data_datetime_to_iso() -> None:
    """Datetime values are serialized to isoformat string."""
    now = datetime.now(timezone.utc)
    data = {"updated_at": now}
    result = serialize_fsm_data(data)
    assert "T" in result["updated_at"]
    assert "Z" in result["updated_at"] or "+" in result["updated_at"]


def test_deserialize_fsm_data_topics_unchanged() -> None:
    """Topics dict is passed through unchanged in blogger flow."""
    data = {"user_id": str(uuid4()), "topics": {"selected": ["a", "b"]}}
    result = deserialize_fsm_data(data, "blogger_registration")
    assert result["topics"] == {"selected": ["a", "b"]}


def test_serialize_fsm_data_none_value() -> None:
    """None values are preserved in serialization."""
    data = {"user_id": uuid4(), "optional_field": None}
    result = serialize_fsm_data(data)
    assert result["optional_field"] is None
    assert result["user_id"] == str(data["user_id"])


def test_deserialize_fsm_data_invalid_uuid_type() -> None:
    """Deserialize with invalid UUID type raises TypeError."""
    import pytest

    data = {"user_id": 12345, "nickname": "test"}
    with pytest.raises(TypeError, match="Cannot parse UUID"):
        deserialize_fsm_data(data, "blogger_registration")


def test_deserialize_fsm_data_uuid_passthrough() -> None:
    """When value is already UUID, pass through unchanged."""
    user_id = uuid4()
    data = {"user_id": user_id, "nickname": "test"}
    result = deserialize_fsm_data(data, "blogger_registration")
    assert result["user_id"] is user_id


def test_deserialize_fsm_data_edit_profile_flow_hits_edit_user_id() -> None:
    """edit_profile flow uses edit_user_id as UUID key."""
    data = {"edit_user_id": str(uuid4()), "other": "val"}
    result = deserialize_fsm_data(data, "edit_profile")
    assert hasattr(result["edit_user_id"], "hex")
    assert result["other"] == "val"


def test_deserialize_fsm_data_unknown_flow_passes_through() -> None:
    """Unknown flow_type: empty uuid_keys/enum_keys, passes values through."""
    data = {"foo": "bar", "num": 42}
    result = deserialize_fsm_data(data, "unknown_flow")
    assert result == {"foo": "bar", "num": 42}
