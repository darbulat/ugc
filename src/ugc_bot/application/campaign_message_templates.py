"""Immutable five-locale invitation catalog; rendering never sends."""

from dataclasses import dataclass
from uuid import UUID

from ugc_bot.domain.campaign_envelope import CampaignEnvelopeV1
from ugc_bot.domain.campaign_review import CampaignDraftContent
from ugc_bot.domain.campaigns import LOCALES, digest


@dataclass(frozen=True, slots=True)
class CampaignMessageTemplates:
    version: str
    entries: tuple[tuple[str, str, str], ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.version, str)
            or not self.version.strip()
            or self.version != self.version.strip()
        ):
            raise ValueError("campaign_template_version_required")
        if type(self.entries) is not tuple or len(self.entries) != len(LOCALES):
            raise ValueError("campaign_five_locale_templates_required")
        for entry in self.entries:
            if (
                type(entry) is not tuple
                or len(entry) != 3
                or any(
                    not isinstance(value, str)
                    or not value.strip()
                    or value != value.strip()
                    or any(ord(char) < 32 or ord(char) == 127 for char in value)
                    for value in entry
                )
            ):
                raise ValueError("campaign_template_entry_invalid")
        if tuple(entry[0] for entry in self.entries) != tuple(sorted(LOCALES)):
            raise ValueError("campaign_five_locale_templates_required")

    @property
    def payload(self) -> dict[str, tuple[str, str]]:
        return {
            locale: (prefix, label) for locale, prefix, label in self.entries
        }

    @property
    def digest(self) -> str:
        return digest(self.payload)


CAMPAIGN_TEMPLATES = CampaignMessageTemplates(
    "campaign-invitation-v1",
    (
        ("be", "Запрашэнне ад", "Паглядзець заданне"),
        ("en", "Invitation from", "View task"),
        ("kk", "Шақыру жіберуші:", "Тапсырманы көру"),
        ("ru", "Приглашение от", "Посмотреть задание"),
        ("uz", "Taklif yuboruvchi:", "Topshiriqni ko‘rish"),
    ),
)


def render_campaign_envelope(
    content: CampaignDraftContent,
    *,
    campaign_id: UUID,
    sender_label: str,
    sender_source: str,
    default_locale: str,
    miniapp_url: str,
    templates: CampaignMessageTemplates = CAMPAIGN_TEMPLATES,
) -> CampaignEnvelopeV1:
    if not isinstance(content, CampaignDraftContent) or not isinstance(
        templates, CampaignMessageTemplates
    ):
        raise ValueError("campaign_typed_render_inputs_required")
    return CampaignEnvelopeV1.render(
        content=content,
        campaign_id=campaign_id,
        sender_label=sender_label,
        sender_source=sender_source,
        template_version=templates.version,
        default_locale=default_locale,
        miniapp_url=miniapp_url,
        templates=templates.payload,
    )
