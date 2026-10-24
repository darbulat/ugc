"""Server wall clock; browser payloads never choose financial command time."""

from datetime import datetime, timezone


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)
