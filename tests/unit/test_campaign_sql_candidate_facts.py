"""SQL string enums retain the same campaign facts as their plain values."""

from enum import Enum

import pytest

from tests.unit.test_campaign_draft_service import candidate
from ugc_bot.application.campaign_moderation_ports import (
    CampaignCandidateFacts,
    CampaignFrozenMap,
)
from ugc_bot.domain.enums import MessengerType, UserStatus, WorkFormat


def test_sql_string_enums_freeze_as_canonical_primitive_values():
    facts = CampaignFrozenMap.from_mapping(
        {
            "actor": {
                "status": UserStatus.ACTIVE,
                "messenger_type": MessengerType.TELEGRAM,
            },
            "profile": {"work_format": WorkFormat.UGC_ONLY},
        }
    )
    plain = CampaignFrozenMap.from_mapping(
        {
            "actor": {"status": "active", "messenger_type": "telegram"},
            "profile": {"work_format": "ugc_only"},
        }
    )
    assert facts == plain and facts.digest == plain.digest
    assert type(facts.payload["actor"]["status"]) is str
    assert type(facts.payload["profile"]["work_format"]) is str


def test_actual_enum_types_preserve_candidate_routing_and_source_identity():
    member = candidate()
    member["context"]["actor"]["messenger_type"] = "telegram"
    plain = CampaignCandidateFacts.from_member(member)
    member["context"]["actor"]["status"] = UserStatus.ACTIVE
    member["context"]["actor"]["messenger_type"] = MessengerType.TELEGRAM
    member["context"]["inviter"]["status"] = UserStatus.ACTIVE
    member["profile"]["work_format"] = WorkFormat.UGC_ONLY
    actual = CampaignCandidateFacts.from_member(member)
    assert actual.scope == plain.scope
    assert actual.source_key == plain.source_key
    assert actual.digest == plain.digest


def test_non_string_enum_remains_unavailable():
    class Unsupported(Enum):
        VALUE = "active"

    with pytest.raises(ValueError, match="^campaign_fact_type_unavailable$"):
        CampaignFrozenMap.from_mapping({"status": Unsupported.VALUE})
