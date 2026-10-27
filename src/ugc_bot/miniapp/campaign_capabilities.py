"""Runtime availability for HTTP hints; commands still enforce authority."""

from ugc_bot.application.campaign_moderation_ports import CampaignCapabilities


async def submission_available(dispatcher, *, session):
    service = dispatcher.get("campaign_submission_service")
    capabilities = getattr(
        getattr(service, "repository", None), "capabilities", None
    )
    if not callable(getattr(service, "submit", None)) or not callable(
        capabilities
    ):
        return False
    ready = await capabilities(session=session)
    return isinstance(ready, CampaignCapabilities) and all(
        value is True
        for value in (ready.context, ready.capacity, ready.persistence)
    )


def delivery_state(config, dispatcher, *, submission_ready):
    flag = getattr(getattr(config, "campaign", None), "delivery_enabled", None)
    moderation = dispatcher.get("campaign_moderation_service")
    responses = dispatcher.get("campaign_response_service")
    if (
        type(flag) is not bool
        or not submission_ready
        or not callable(getattr(moderation, "decide", None))
        or not all(
            callable(getattr(responses, method, None))
            for method in ("view", "respond", "report")
        )
    ):
        return "unavailable"
    return "enabled" if flag else "paused"
