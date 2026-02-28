"""Random delay helpers for Instagram API requests (anti-bot behavior)."""

import random


def random_delay_seconds(
    base_seconds: float,
    min_factor: float = 0.6,
    max_factor: float = 1.6,
) -> float:
    """Return a random delay in seconds to avoid fixed-interval bot pattern.

    Args:
        base_seconds: Base delay in seconds (e.g. configured delay).
        min_factor: Minimum multiplier (default 0.6 → 60% of base).
        max_factor: Maximum multiplier (default 1.6 → 160% of base).

    Returns:
        base_seconds * uniform(min_factor, max_factor), minimum 0.1.
    """
    delay = base_seconds * random.uniform(min_factor, max_factor)
    return max(0.1, delay)
