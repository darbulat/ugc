"""Service for checking order content against banned categories."""

import re
from dataclasses import dataclass

# Patterns with word boundaries to avoid false positives
_BANNED_PATTERNS = [
    re.compile(r"\bказино\b", re.IGNORECASE),
    re.compile(r"\bcasino\b", re.IGNORECASE),
    re.compile(r"\bгэмблинг\b", re.IGNORECASE),
    re.compile(r"\bgambling\b", re.IGNORECASE),
    re.compile(r"\bгемблинг\b", re.IGNORECASE),
    re.compile(r"\bбукмекер\w*\b", re.IGNORECASE),
    re.compile(r"\bbetting\b", re.IGNORECASE),
    re.compile(r"\bтотализатор\b", re.IGNORECASE),
    re.compile(r"\bслоты\b", re.IGNORECASE),
    re.compile(r"\bslots\b", re.IGNORECASE),
    re.compile(r"\bрулетк\w*\b", re.IGNORECASE),
    re.compile(r"\broulette\b", re.IGNORECASE),
    re.compile(r"\b1xbet\b", re.IGNORECASE),
    re.compile(r"\b1хбет\b", re.IGNORECASE),
    re.compile(r"\bfonbet\b", re.IGNORECASE),
    re.compile(r"\bleon\b", re.IGNORECASE),
    re.compile(r"\bparimatch\b", re.IGNORECASE),
    re.compile(r"\bmelbet\b", re.IGNORECASE),
    re.compile(r"\bwinline\b", re.IGNORECASE),
]


@dataclass(slots=True)
class ContentModerationService:
    """Check order text fields for banned content (casino, gambling, etc.)."""

    def contains_banned_content(self, text: str | None) -> bool:
        """Return True if text contains banned keywords or patterns."""
        if not text or not text.strip():
            return False
        text_lower = text.lower().strip()
        return any(pattern.search(text_lower) for pattern in _BANNED_PATTERNS)

    def get_banned_matches(self, text: str | None) -> list[str]:
        """Return list of banned matches found in text for error display."""
        if not text or not text.strip():
            return []
        matches: list[str] = []
        text_lower = text.lower().strip()
        for pattern in _BANNED_PATTERNS:
            for m in pattern.finditer(text_lower):
                matches.append(m.group())
        return list(dict.fromkeys(matches))

    def order_contains_banned_content(
        self,
        product_link: str | None = None,
        offer_text: str | None = None,
        barter_description: str | None = None,
        content_usage: str | None = None,
        geography: str | None = None,
    ) -> bool:
        """Check all order text fields for banned content."""
        for text in (
            product_link,
            offer_text,
            barter_description,
            content_usage,
            geography,
        ):
            if self.contains_banned_content(text):
                return True
        return False

    def get_order_banned_matches(
        self,
        product_link: str | None = None,
        offer_text: str | None = None,
        barter_description: str | None = None,
        content_usage: str | None = None,
        geography: str | None = None,
    ) -> list[str]:
        """Return all banned matches across order text fields."""
        all_matches: list[str] = []
        for text in (
            product_link,
            offer_text,
            barter_description,
            content_usage,
            geography,
        ):
            all_matches.extend(self.get_banned_matches(text))
        return list(dict.fromkeys(all_matches))
