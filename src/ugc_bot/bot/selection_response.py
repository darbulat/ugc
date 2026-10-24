"""Native UI messages for server-owned selection rejection reasons."""


def selection_response_message_key(reason: str) -> str:
    if reason == "selection_verified_creator_required":
        return "msg_offer_response_verification_required"
    if reason == "selection_identity_already_interested":
        return "msg_offer_response_identity_used"
    return "msg_offer_response_unavailable"
