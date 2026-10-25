"""Durable campaign documents restore only explicit immutable contracts."""

import importlib

import pytest

from tests.unit.test_campaign_submission_service import (
    SyntheticCampaignRepository,
)


def codec():
    return importlib.import_module("ugc_bot.infrastructure.campaign_codec")


def test_runtime_state_and_candidates_roundtrip_without_losing_provenance():
    repo = SyntheticCampaignRepository()
    values = (next(iter(repo.states.values())), tuple(repo.members), repo.facts)
    for value in values:
        assert codec().decode(codec().encode(value)) == value


def test_codec_cannot_construct_arbitrary_classes_or_accept_unknown_fields():
    with pytest.raises(ValueError):
        codec().decode({"type": "os.system", "values": {}})
    state = next(iter(SyntheticCampaignRepository().states.values()))
    document = codec().encode(state)
    document["values"]["unexpected"] = "forged"
    with pytest.raises(ValueError):
        codec().decode(document)


def test_runtime_schema_exposes_provenance_and_immutable_outcomes():
    module = importlib.import_module(
        "ugc_bot.infrastructure.db.campaign_runtime_schema"
    )
    import sqlalchemy as sa

    tables = module.runtime_tables(sa.MetaData())
    names = {table.name for table in tables}
    assert {
        "campaign_runtime_commands",
        "campaign_runtime_jobs",
        "campaign_runtime_attempts",
        "campaign_runtime_outcomes",
        "campaign_runtime_responses",
    } <= names
    assert "BEFORE UPDATE OR DELETE OR TRUNCATE" in module.immutability_sql(
        tables
    )


@pytest.mark.parametrize(
    "document",
    [
        [],
        {"type": "uuid", "value": "bad"},
        {"type": "datetime", "value": "2026-10-25"},
        {"type": "unknown", "value": 0},
        {"type": "dict", "value": [["same", 1], ["same", 2]]},
        {"type": "list", "value": "bad"},
    ],
)
def test_corrupt_retained_documents_fail_closed(document):
    with pytest.raises(ValueError, match="campaign_document_invalid"):
        codec().decode(document)


def test_codec_preserves_primitive_enums_and_explicit_list_shapes():
    from enum import StrEnum

    class Status(StrEnum):
        VALUE = "value"

    assert codec().encode(Status.VALUE) == "value"
    assert codec().decode(codec().encode([1, "label", None, False])) == [
        1,
        "label",
        None,
        False,
    ]
    with pytest.raises(ValueError, match="campaign_document_invalid"):
        codec().encode(object())
