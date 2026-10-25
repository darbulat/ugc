"""Strict JSON codec for the closed set of immutable campaign fact contracts."""

from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from ugc_bot.application import campaign_moderation_ports as ports
from ugc_bot.application import campaign_runtime_ports
from ugc_bot.domain import (
    campaign_capacity,
    campaign_envelope,
    campaign_moderation,
    campaign_review,
)
from ugc_bot.domain.financial import utc

_MODULES = (
    ports,
    campaign_runtime_ports,
    campaign_capacity,
    campaign_envelope,
    campaign_moderation,
    campaign_review,
)
_TYPES = {
    value.__name__: value
    for module in _MODULES
    for value in vars(module).values()
    if isinstance(value, type)
    and is_dataclass(value)
    and value.__module__ == module.__name__
}


def encode(value):
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, str):
        return str(value)
    if value is None or type(value) in (str, int, bool, float):
        return value
    if isinstance(value, UUID):
        return {"type": "uuid", "value": str(value)}
    if isinstance(value, datetime):
        return {"type": "datetime", "value": utc(value).isoformat()}
    if type(value) in (tuple, list):
        return {
            "type": "tuple" if type(value) is tuple else "list",
            "value": [encode(item) for item in value],
        }
    if type(value) is dict:
        return {
            "type": "dict",
            "value": [[encode(k), encode(v)] for k, v in value.items()],
        }
    if type(value).__name__ in _TYPES and _TYPES[type(value).__name__] is type(
        value
    ):
        return {
            "type": type(value).__name__,
            "values": {
                f.name: encode(getattr(value, f.name)) for f in fields(value)
            },
        }
    raise ValueError("campaign_document_invalid")


def decode(value):
    if value is None or type(value) in (str, int, bool, float):
        return value
    if type(value) is not dict:
        raise ValueError("campaign_document_invalid")
    kind = value.get("type")
    try:
        if kind in _TYPES and set(value) == {"type", "values"}:
            cls = _TYPES[kind]
            if type(value["values"]) is not dict or set(value["values"]) != {
                f.name for f in fields(cls)
            }:
                raise ValueError("campaign_document_invalid")
            return cls(**{k: decode(v) for k, v in value["values"].items()})
        if set(value) != {"type", "value"}:
            raise ValueError("campaign_document_invalid")
        return _decode_value(kind, value["value"])
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise ValueError("campaign_document_invalid") from error
    raise ValueError("campaign_document_invalid")


def _decode_value(kind, data):
    if kind == "uuid":
        return UUID(data)
    if kind == "datetime":
        return utc(datetime.fromisoformat(data))
    if kind in ("tuple", "list") and type(data) is list:
        rows = [decode(item) for item in data]
        return tuple(rows) if kind == "tuple" else rows
    if kind == "dict" and type(data) is list:
        pairs = [(decode(k), decode(v)) for k, v in data]
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ValueError("campaign_document_invalid")
        return result
    raise ValueError("campaign_document_invalid")
