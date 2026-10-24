"""Readable publication inputs; no legal content or recipient defaults."""

from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class TermsDocumentInput:
    document_id: UUID | None = None
    content_text: str | None = None
    source_locale: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class PayoutFieldDefinition:
    key: str
    labels: dict[str, str]
    help: dict[str, str] = field(default_factory=dict)
    allowed_values: tuple[str, ...] | None = None
