"""Serialize and deserialize FSM draft data for JSONB storage."""

from datetime import datetime
from uuid import UUID

from ugc_bot.domain.enums import AudienceGender, WorkFormat


def serialize_fsm_data(data: dict) -> dict:
    """Convert FSM data to JSON-serializable dict (UUID -> str, enum -> value)."""

    result: dict = {}
    for key, value in data.items():
        result[key] = _serialize_value(value)
    return result


def _serialize_value(value: object) -> object:
    """Recursively serialize a single value."""
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_value(item) for item in value]
    if hasattr(value, "value") and not isinstance(
        value, (str, int, float, bool, type(None))
    ):  # pragma: no cover
        return getattr(value, "value")
    return value  # pragma: no cover


def deserialize_fsm_data(data: dict, flow_type: str) -> dict:
    """Convert stored JSON-like data back to FSM-ready types for the given flow."""

    result: dict = {}
    uuid_keys = _uuid_keys_for_flow(flow_type)
    enum_keys = _enum_keys_for_flow(flow_type)

    for key, value in data.items():
        if key in uuid_keys and value is not None:
            result[key] = _parse_uuid(value)
        elif key in enum_keys and value is not None:
            enum_cls = enum_keys[key]
            result[key] = enum_cls(value) if isinstance(value, str) else value
        elif isinstance(value, dict) and key == "topics":
            result[key] = value
        else:
            result[key] = value
    return result


def _uuid_keys_for_flow(flow_type: str) -> set[str]:
    """Keys that store UUID in this flow."""
    if flow_type == "blogger_registration":
        return {"user_id"}
    if flow_type == "advertiser_registration":
        return {"user_id"}
    if flow_type == "order_creation":
        return {"user_id"}
    if flow_type == "edit_profile":  # pragma: no cover
        return {"edit_user_id"}
    return set()  # pragma: no cover


def _enum_keys_for_flow(flow_type: str) -> dict[str, type]:
    """Keys that store enum (by value) in this flow."""
    if flow_type == "blogger_registration":
        return {"audience_gender": AudienceGender, "work_format": WorkFormat}
    return {}  # pragma: no cover


def _parse_uuid(value: object) -> UUID:
    """Parse UUID from string or return as-is if already UUID."""
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    raise TypeError(f"Cannot parse UUID from {type(value)}")  # pragma: no cover
