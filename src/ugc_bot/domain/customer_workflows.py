"""Customer request contracts shared by bot and signed Mini App callers."""

from typing import Literal, Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

ServiceCode = Literal[
    "selection", "accompaniment", "regular_search", "ambassadors", "result"
]
CATALOG = (
    {"code": "selection", "title": "Автоподбор", "mode": "order"},
    {"code": "accompaniment", "title": "Подбор под ключ", "mode": "order"},
    {"code": "regular_search", "title": "Регулярный поиск", "mode": "lead"},
    {"code": "ambassadors", "title": "Ведение амбассадоров", "mode": "lead"},
    {"code": "result", "title": "Оплата за результат", "mode": "assessment"},
)
RESULT_REQUIRED = (
    "name",
    "telegram",
    "company",
    "niche",
    "product",
    "expected_benefit",
)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Attachment(Contract):
    reference: str = Field(min_length=1, max_length=2048)
    label: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def safe_reference(self) -> Self:
        url = urlsplit(self.reference)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
        ):
            raise ValueError("attachment_reference_invalid")
        return self


class SupportInput(Contract):
    order_id: UUID
    operation_key: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=4000)
    contact_reference: str = Field(min_length=1, max_length=500)
    blogger_id: UUID | None = None
    attachments: list[Attachment] = Field(default_factory=list, max_length=10)


class ServiceParameters(Contract):
    name: str = Field(default="", max_length=200)
    telegram: str = Field(default="", max_length=200)
    company: str = Field(default="", max_length=500)
    niche: str = Field(default="", max_length=500)
    product: str = Field(default="", max_length=2000)
    expected_benefit: str = Field(default="", max_length=4000)
    website: str | None = Field(default=None, max_length=2048)
    geography: str | None = Field(default=None, max_length=500)
    average_check: str | None = Field(default=None, max_length=500)
    margin_or_cac: str | None = Field(default=None, max_length=500)
    current_sales: str | None = Field(default=None, max_length=1000)
    goal: str | None = Field(default=None, max_length=1000)
    tracking: str | None = Field(default=None, max_length=1000)


class ServiceLeadInput(Contract):
    service_code: ServiceCode
    operation_key: str = Field(min_length=1, max_length=256)
    contact_reference: str = Field(min_length=1, max_length=500)
    source: str = Field(min_length=1, max_length=200)
    order_id: UUID | None = None
    parameters: ServiceParameters
    consent: bool

    @model_validator(mode="after")
    def result_fields(self) -> Self:
        if not self.consent:
            raise ValueError("service_consent_required")
        if self.service_code == "result" and any(
            not getattr(self.parameters, field) for field in RESULT_REQUIRED
        ):
            raise ValueError("result_fields_required")
        return self
