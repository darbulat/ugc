"""Public request contracts normalize idempotent input and require consent."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from ugc_bot.domain.customer_workflows import ServiceLeadInput, SupportInput


def test_support_normalizes_text_and_requires_reason():
    value = SupportInput(
        order_id=uuid4(),
        operation_key=" x ",
        reason=" why ",
        contact_reference=" @me ",
    )
    assert (value.operation_key, value.reason, value.contact_reference) == (
        "x",
        "why",
        "@me",
    )
    with pytest.raises(ValidationError):
        SupportInput(
            order_id=uuid4(),
            operation_key="x",
            reason=" ",
            contact_reference="me",
        )


def test_result_requires_six_fields_and_separate_consent():
    data = dict(
        service_code="result",
        operation_key="x",
        contact_reference="@me",
        source="miniapp",
        parameters={},
    )
    with pytest.raises(ValidationError):
        ServiceLeadInput(**data, consent=True)
    data["parameters"] = dict(
        name="Name",
        telegram="@me",
        company="Brand",
        niche="Beauty",
        product="Cream",
        expected_benefit="Leads",
    )
    with pytest.raises(ValidationError):
        ServiceLeadInput(**data, consent=False)
    assert ServiceLeadInput(**data, consent=True).parameters.product == "Cream"


def test_attachment_rejects_local_or_privileged_references():
    with pytest.raises(ValidationError):
        SupportInput(
            order_id=uuid4(),
            operation_key="x",
            reason="why",
            contact_reference="me",
            attachments=[dict(reference="file:///etc/passwd", label="a")],
        )


def test_support_attachment_is_a_named_external_link():
    value = SupportInput(
        order_id=uuid4(),
        operation_key="attachment",
        reason="Help",
        contact_reference="@me",
        attachments=[
            {
                "reference": "https://example.test/evidence.jpg",
                "label": "Evidence",
            }
        ],
    )
    assert value.attachments[0].label == "Evidence"
