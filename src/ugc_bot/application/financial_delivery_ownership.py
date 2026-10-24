"""Financial namespace events owned by separate control/transport workers."""

SEPARATE_DELIVERY_EVENT_TYPES = (
    "financial.capture_intent",
    "financial.collaboration.notice_requested",
)
