"""Per-build call budgets.

Every source gets a fixed number of calls per build. On top of that, the budget watches the
rate-limit headers the API returns and closes itself before touching the reserve.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


class BudgetExhaustedError(Exception):
    def __init__(self, name: str, reason: str) -> None:
        super().__init__(f"{name}: {reason}")
        self.name = name
        self.reason = reason


@dataclass(slots=True)
class Budget:
    name: str
    limit: int
    min_interval: float = 0.0
    reserve_fraction: float = 0.10
    used: int = 0
    calls: int = 0
    last_call_at: float | None = None
    closed_reason: str | None = None
    observed_remaining: int | None = None
    observed_limit: int | None = None
    events: list[str] = field(default_factory=list)

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    @property
    def closed(self) -> bool:
        return self.closed_reason is not None

    def can_spend(self, cost: int = 1) -> bool:
        return not self.closed and self.used + cost <= self.limit

    def ensure(self, cost: int = 1) -> None:
        if self.closed:
            raise BudgetExhaustedError(self.name, self.closed_reason or "closed")
        if self.used + cost > self.limit:
            raise BudgetExhaustedError(self.name, f"budget of {self.limit} reached")

    def spend(self, cost: int = 1) -> None:
        self.used += cost
        self.calls += 1

    def close(self, reason: str) -> None:
        if self.closed_reason is None:
            self.closed_reason = reason
            self.events.append(reason)

    def cap(self, api_remaining: int, api_limit: int) -> None:
        """Shrink the budget so it never eats into the API's reserve (pre-flight check)."""
        reserve = math.ceil(api_limit * self.reserve_fraction)
        allowed = max(0, api_remaining - reserve)
        if allowed < self.remaining:
            self.limit = self.used + allowed
            self.events.append(f"capped to {self.limit} (api remaining {api_remaining})")
        self.observed_remaining = api_remaining
        self.observed_limit = api_limit

    def observe(self, remaining: int | None, limit: int | None) -> None:
        """Close the budget when the API reports that only the reserve is left."""
        if remaining is None:
            return
        self.observed_remaining = remaining
        if limit:
            self.observed_limit = limit
        ref_limit = limit or self.observed_limit
        reserve = math.ceil(ref_limit * self.reserve_fraction) if ref_limit else 0
        if remaining <= reserve:
            self.close(f"api reserve reached (remaining {remaining})")

    def report(self) -> dict[str, object]:
        return {
            "budget": self.limit,
            "used": self.used,
            "calls": self.calls,
            "closed": self.closed_reason,
            "api_remaining": self.observed_remaining,
        }
