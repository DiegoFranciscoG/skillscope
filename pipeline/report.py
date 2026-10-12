"""Per-source status for the build report (``index.json → sources``)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class SourceReport:
    id: str
    status: str = "ok"  # ok | partial | failed | skipped
    reason: str | None = None
    calls: int = 0
    budget: int = 0
    duration_ms: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {k: v for k, v in data.items() if v not in (None, {}, [])}
