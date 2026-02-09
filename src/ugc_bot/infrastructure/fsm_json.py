"""JSON serialization for FSM storage (UUID, datetime support)."""

import json
from datetime import datetime
from uuid import UUID


class _UUIDEncoder(json.JSONEncoder):
    """JSON encoder that handles UUID and datetime objects."""

    def default(self, obj: object) -> object:
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def fsm_json_dumps(obj: dict) -> str:
    """Serialize dict to JSON with UUID and datetime support."""
    return json.dumps(obj, cls=_UUIDEncoder)


def fsm_json_loads(data: str) -> dict:
    """Deserialize JSON string to dict for FSM data."""
    return json.loads(data)
