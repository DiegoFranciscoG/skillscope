"""Time source abstraction so the pipeline can be tested without real waits."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


class FakeClock:
    """Deterministic clock: sleeping only advances the internal time."""

    def __init__(self, start: datetime) -> None:
        self._now = start
        self._mono = 0.0
        self.slept: list[float] = []

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        self.slept.append(seconds)
        self.advance(seconds)

    def advance(self, seconds: float) -> None:
        self._mono += seconds
        self._now += timedelta(seconds=seconds)


def iso(dt: datetime) -> str:
    """ISO 8601 in UTC with a trailing Z and second precision."""
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def days_between(earlier: datetime | None, later: datetime) -> float | None:
    if earlier is None:
        return None
    return max(0.0, (later - earlier).total_seconds() / 86400.0)


class InstantClock(SystemClock):
    """Real wall clock where sleeping is skipped (offline builds against the sample API)."""

    def __init__(self) -> None:
        self._offset = 0.0

    def now(self) -> datetime:
        return super().now() + timedelta(seconds=self._offset)

    def monotonic(self) -> float:
        return super().monotonic() + self._offset

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            self._offset += seconds
