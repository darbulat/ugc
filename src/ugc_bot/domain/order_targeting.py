"""Validated intake filters shared with the existing creator matcher."""

from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

from ugc_bot.domain.enums import BloggerGender
from ugc_bot.domain.social import SocialPlatform


def validate_range(low, high, maximum):
    if any(
        value is not None
        and (type(value) is not int or not 0 <= value <= maximum)
        for value in (low, high)
    ):
        raise ValueError("invalid_targeting_range")
    if low is not None and high is not None and low > high:
        raise ValueError("invalid_targeting_range")


@dataclass(frozen=True, slots=True)
class OrderTargeting:
    min_followers: int | None = None
    max_followers: int | None = None
    min_age: int | None = None
    max_age: int | None = None
    gender: str | None = None
    city: str | None = None
    platforms: tuple[str, ...] = ()
    content_usage: str | None = None
    brief_link: str | None = None
    deadlines: str | None = None
    geography: str | None = None

    def __post_init__(self):
        validate_range(self.min_followers, self.max_followers, 2147483647)
        validate_range(self.min_age, self.max_age, 120)
        if self.gender is not None:
            object.__setattr__(self, "gender", BloggerGender(self.gender).value)
        for name, limit in (
            ("city", 200),
            ("geography", 200),
            ("content_usage", 4000),
            ("brief_link", 2048),
            ("deadlines", 4000),
        ):
            value = getattr(self, name)
            if value is not None:
                if (
                    not isinstance(value, str)
                    or not value.strip()
                    or len(value) > limit
                ):
                    raise ValueError("invalid_targeting_brief")
                object.__setattr__(self, name, value.strip())
        if self.city is not None and self.geography is not None:
            raise ValueError("ambiguous_targeting_geography")
        if self.brief_link is not None:
            parsed = urlsplit(self.brief_link)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username
            ):
                raise ValueError("invalid_targeting_brief_link")
        if (
            not isinstance(self.platforms, tuple)
            or len(self.platforms) > 5
            or len(set(self.platforms)) != len(self.platforms)
        ):
            raise ValueError("invalid_targeting_platforms")
        object.__setattr__(
            self,
            "platforms",
            tuple(sorted(SocialPlatform(p).value for p in self.platforms)),
        )

    def order_fields(self) -> dict:
        values = asdict(self)
        if values["deadlines"] is None:
            values.pop("deadlines")
        city = values.pop("city")
        values["geography"] = values["geography"] or city
        values.pop("platforms")
        gender = values.pop("gender")
        values["required_blogger_gender"] = (
            BloggerGender(gender) if gender is not None else None
        )
        return values

    def payload(self) -> dict:
        """Keep historical hashes stable when no preview deadline is set."""
        values = asdict(self)
        if values["deadlines"] is None:
            values.pop("deadlines")
        if values["geography"] is None:
            values.pop("geography")
        return values
