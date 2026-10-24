"""Future submission seal: exact all-locale bytes, never a draft send."""

from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID

from ugc_bot.domain.campaign_review import https_url, nonblank
from ugc_bot.domain.campaigns import LOCALES, digest


@dataclass(frozen=True, slots=True)
class LocaleEnvelope:
    locale: str
    text: str
    action_url: str
    action_label: str

    def __post_init__(self):
        if self.locale not in LOCALES:
            raise ValueError("campaign_locale_invalid")
        nonblank(self.text)
        if (
            len(self.text) > 4096
            or len(self.text.encode("utf-16-le")) // 2 > 4096
        ):
            raise ValueError("campaign_technical_message_limit")
        if self.action_url != https_url(self.action_url):
            raise ValueError("campaign_native_action_invalid")
        nonblank(self.action_label)
        if any(
            ord(char) < 32 or ord(char) == 127 for char in self.action_label
        ):
            raise ValueError("campaign_native_action_invalid")

    @property
    def payload(self):
        return {
            "channel": "telegram",
            "text": self.text,
            "action_url": self.action_url,
            "action_label": self.action_label,
            "parse_mode": None,
        }

    @property
    def digest(self):
        return digest(self.payload)


@dataclass(frozen=True, slots=True)
class CampaignEnvelopeV1:
    campaign_id: UUID
    sender_label: str
    sender_source: str
    template_version: str
    template_digest: str
    default_locale: str
    locales: tuple[LocaleEnvelope, ...]

    def __post_init__(self):
        if not isinstance(self.campaign_id, UUID) or not self.campaign_id.int:
            raise ValueError("campaign_uuid_required")
        if (
            type(self.locales) is not tuple
            or len(self.locales) != len(LOCALES)
            or any(
                not isinstance(value, LocaleEnvelope) for value in self.locales
            )
            or {value.locale for value in self.locales} != LOCALES
            or self.default_locale not in LOCALES
        ):
            raise ValueError("campaign_five_locale_envelope_required")
        for value in (
            self.sender_label,
            self.sender_source,
            self.template_version,
        ):
            nonblank(value)
        if (
            not isinstance(self.template_digest, str)
            or len(self.template_digest) != 64
            or any(
                char not in "0123456789abcdef" for char in self.template_digest
            )
        ):
            raise ValueError("campaign_template_digest_required")
        actions = {value.action_url for value in self.locales}
        if len(actions) != 1:
            raise ValueError("campaign_native_action_invalid")
        parsed = urlsplit(next(iter(actions)))
        if parsed.fragment or parsed.query != f"campaign={self.campaign_id}":
            raise ValueError("campaign_native_action_invalid")

    @classmethod
    def render(
        cls,
        *,
        content,
        campaign_id,
        sender_label,
        sender_source,
        template_version,
        default_locale,
        miniapp_url,
        templates,
    ):
        if not isinstance(campaign_id, UUID) or not campaign_id.int:
            raise ValueError("campaign_uuid_required")
        if set(templates) != LOCALES or default_locale not in LOCALES:
            raise ValueError("campaign_five_locale_envelope_required")
        base = https_url(miniapp_url)
        if urlsplit(base).query or urlsplit(base).fragment:
            raise ValueError("campaign_native_base_invalid")
        sender = nonblank(sender_label)
        action = f"{base}?campaign={campaign_id}"
        locales = []
        for locale in sorted(LOCALES):
            prefix, label = templates[locale]
            prefix, label = nonblank(prefix), nonblank(label)
            text = f"{prefix} {sender}\n\n{content.title}\n\n{content.text}"
            if content.link is not None:
                text += "\n\n" + content.link
            locales.append(LocaleEnvelope(locale, text, action, label))
        return cls(
            campaign_id,
            sender,
            nonblank(sender_source),
            nonblank(template_version),
            digest(templates),
            default_locale,
            tuple(locales),
        )

    @property
    def payload(self):
        return {
            "schema": "campaign-envelope-v1",
            "campaign_id": str(self.campaign_id),
            "sender_label": self.sender_label,
            "sender_source": self.sender_source,
            "template_version": self.template_version,
            "template_digest": self.template_digest,
            "default_locale": self.default_locale,
            "locales": {value.locale: value.payload for value in self.locales},
            "locale_digests": {
                value.locale: value.digest for value in self.locales
            },
        }

    @property
    def digest(self):
        return digest(self.payload)
