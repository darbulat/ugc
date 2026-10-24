"""Strict, immutable draft and segment intent without audience overrides."""

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID

from ugc_bot.domain.campaigns import digest
from ugc_bot.domain.enums import WorkFormat
from ugc_bot.domain.social import SocialPlatform


def fields(value, required=(), optional=()):
    if (
        type(value) is not dict
        or set(value) - set(required) - set(optional)
        or set(required) - set(value)
        or any(v is None for v in value.values())
    ):
        raise ValueError("campaign_unexpected_fields")


def nonblank(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("campaign_text_required")
    return value.strip()


def token(value):
    return " ".join(nonblank(value).lower().replace("ё", "е").split())


def https_url(value):
    value = nonblank(value)
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)
            or host.rstrip(".").lower()
            in ("localhost", "localhost.localdomain")
            or host.lower().endswith(".localhost")
        ):
            raise ValueError("invalid_https")
        _ = parsed.port
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError("private_https")
    except ValueError as exc:
        raise ValueError("campaign_https_link_required") from exc
    return value


@dataclass(frozen=True, slots=True)
class CampaignDraftContent:
    title: str
    text: str
    link: str | None = None

    def __post_init__(self):
        if self.title != nonblank(self.title) or self.text != nonblank(
            self.text
        ):
            raise ValueError("campaign_content_not_canonical")
        if self.link is not None and self.link != https_url(self.link):
            raise ValueError("campaign_link_not_canonical")

    @classmethod
    def parse(cls, payload):
        fields(payload, ("title", "text"), ("link",))
        return cls(
            nonblank(payload["title"]),
            nonblank(payload["text"]),
            https_url(payload["link"]) if "link" in payload else None,
        )

    def validate(self, limits):
        for field in ("title", "text", "link"):
            bound = limits.get(field + "_max_chars")
            if type(bound) is not int or bound < 1:
                raise ValueError("campaign_content_limits_required")
            if len(getattr(self, field) or "") > bound:
                raise ValueError("campaign_content_limit_exceeded")

    @property
    def payload(self):
        result = {"title": self.title, "text": self.text}
        if self.link is not None:
            result["link"] = self.link
        return result


@dataclass(frozen=True, slots=True)
class CampaignSocialFilter:
    platform: str
    work_format: str | None = None
    followers_min: int | None = None
    followers_max: int | None = None

    def __post_init__(self):
        SocialPlatform(self.platform)
        if self.work_format is not None:
            WorkFormat(self.work_format)
        for value in (self.followers_min, self.followers_max):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("campaign_follower_range_invalid")
        if (
            self.followers_min is not None
            and self.followers_max is not None
            and self.followers_min > self.followers_max
        ):
            raise ValueError("campaign_follower_range_invalid")

    @classmethod
    def parse(cls, payload):
        fields(
            payload,
            ("platform",),
            ("work_format", "followers_min", "followers_max"),
        )
        platform = SocialPlatform(payload["platform"]).value
        work = (
            WorkFormat(payload["work_format"]).value
            if "work_format" in payload
            else None
        )
        minimum, maximum = (
            payload.get("followers_min"),
            payload.get("followers_max"),
        )
        return cls(platform, work, minimum, maximum)

    @property
    def numeric(self):
        return self.followers_min is not None or self.followers_max is not None

    @property
    def payload(self):
        return {
            key: value
            for key, value in (
                ("platform", self.platform),
                ("work_format", self.work_format),
                ("followers_min", self.followers_min),
                ("followers_max", self.followers_max),
            )
            if value is not None
        }


@dataclass(frozen=True, slots=True)
class CampaignSegmentV1:
    country: str | None = None
    region: str | None = None
    city: str | None = None
    topics_any: tuple[str, ...] = ()
    profile_work_format: str | None = None
    social: CampaignSocialFilter | None = None

    def __post_init__(self):
        for value in (self.country, self.region, self.city):
            if value is not None and value != token(value):
                raise ValueError("campaign_segment_not_canonical")
        if type(self.topics_any) is not tuple or self.topics_any != tuple(
            sorted({token(value) for value in self.topics_any})
        ):
            raise ValueError("campaign_topics_not_canonical")
        if self.profile_work_format is not None:
            WorkFormat(self.profile_work_format)
        if self.social is not None and not isinstance(
            self.social, CampaignSocialFilter
        ):
            raise ValueError("campaign_typed_social_filter_required")

    @classmethod
    def parse(cls, payload):
        fields(
            payload,
            optional=(
                "country",
                "region",
                "city",
                "topics_any",
                "profile_work_format",
                "social",
            ),
        )
        topics = payload.get("topics_any", [])
        if type(topics) is not list or ("topics_any" in payload and not topics):
            raise ValueError("campaign_topics_invalid")
        geography = {
            key: token(payload[key])
            for key in ("country", "region", "city")
            if key in payload
        }
        return cls(
            **geography,
            topics_any=tuple(sorted({token(value) for value in topics})),
            profile_work_format=WorkFormat(payload["profile_work_format"]).value
            if "profile_work_format" in payload
            else None,
            social=CampaignSocialFilter.parse(payload["social"])
            if "social" in payload
            else None,
        )

    @property
    def payload(self):
        result = {
            key: value
            for key, value in (
                ("country", self.country),
                ("region", self.region),
                ("city", self.city),
                ("profile_work_format", self.profile_work_format),
            )
            if value is not None
        }
        if self.topics_any:
            result["topics_any"] = list(self.topics_any)
        if self.social is not None:
            result["social"] = self.social.payload
        return result

    @property
    def digest(self):
        return digest(
            {"schema": "campaign-segment-v1", "segment": self.payload}
        )


@dataclass(frozen=True, slots=True)
class SaveCampaignDraft:
    actor_id: UUID
    operation_key: str
    expected_version: int
    campaign_id: UUID | None
    policy_version: int
    terms_hash: str
    content: CampaignDraftContent
    segment: CampaignSegmentV1

    def __post_init__(self):
        if (
            not isinstance(self.actor_id, UUID)
            or not self.actor_id.int
            or (
                self.campaign_id is not None
                and (
                    not isinstance(self.campaign_id, UUID)
                    or not self.campaign_id.int
                )
            )
            or type(self.expected_version) is not int
            or self.expected_version < 0
            or (self.campaign_id is None and self.expected_version != 0)
            or type(self.policy_version) is not int
            or self.policy_version < 1
            or not isinstance(self.terms_hash, str)
            or len(self.terms_hash) != 64
            or any(c not in "0123456789abcdef" for c in self.terms_hash)
            or len(nonblank(self.operation_key)) > 256
            or not isinstance(self.content, CampaignDraftContent)
            or not isinstance(self.segment, CampaignSegmentV1)
        ):
            raise ValueError("campaign_draft_intent_invalid")

    @classmethod
    def parse(cls, actor_id, payload):
        values = dict(payload)
        identifier = values.pop("campaign_id", None)
        fields(
            values,
            (
                "operation_key",
                "expected_version",
                "policy_version",
                "terms_hash",
                "content",
                "segment",
            ),
        )
        campaign_id = UUID(str(identifier)) if identifier is not None else None
        return cls(
            actor_id,
            values["operation_key"],
            values["expected_version"],
            campaign_id,
            values["policy_version"],
            values["terms_hash"],
            CampaignDraftContent.parse(values["content"]),
            CampaignSegmentV1.parse(values["segment"]),
        )

    @property
    def payload_hash(self):
        return digest(
            {
                "action": "save_draft",
                "expected_version": self.expected_version,
                "campaign_id": str(self.campaign_id)
                if self.campaign_id
                else None,
                "policy_version": self.policy_version,
                "terms_hash": self.terms_hash,
                "content": self.content.payload,
                "segment": self.segment.payload,
            }
        )
