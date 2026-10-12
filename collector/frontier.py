"""Queue of repositories waiting to be analyzed, ordered by a simple priority."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from collector.state import StateStore
from pipeline.clock import days_between, iso, parse_iso


def priority(stars: int, via_count: int, pushed_at: str | None, now: datetime) -> float:
    """``log10(1 + stars) + 0.5·channels + 0.3·recency`` (see docs/fuentes.md §3)."""
    age = days_between(parse_iso(pushed_at), now)
    recency = 0.0 if age is None else math.pow(2.0, -age / 30.0)
    return round(math.log10(1 + max(0, stars)) + 0.5 * via_count + 0.3 * recency, 4)


class Frontier:
    def __init__(self, state: StateStore, now: datetime) -> None:
        self.state = state
        self.now = now
        raw = state.data.get("frontier")
        if isinstance(raw, list):  # legacy list form
            raw = {str(c["id"]).lower(): c for c in raw if isinstance(c, dict) and "id" in c}
        self.items: dict[str, dict[str, Any]] = raw if isinstance(raw, dict) else {}
        state.data["frontier"] = self.items

    def add(
        self,
        repo_id: str,
        *,
        via: str,
        stars: int = 0,
        pushed_at: str | None = None,
        excluded: set[str] | None = None,
    ) -> bool:
        key = repo_id.lower()
        if excluded and key in excluded:
            return False
        known = self.state.known_repo(repo_id)
        if known and known.get("status") in {"opted_out", "gone"}:
            return False
        entry = self.items.get(key)
        if entry is None:
            entry = {
                "id": repo_id,
                "via": [],
                "stars": 0,
                "pushed_at": None,
                "added_at": iso(self.now),
            }
            self.items[key] = entry
        if via not in entry["via"]:
            entry["via"].append(via)
        entry["stars"] = max(int(entry.get("stars") or 0), stars)
        if pushed_at and (entry.get("pushed_at") or "") < pushed_at:
            entry["pushed_at"] = pushed_at
        entry["priority"] = priority(
            entry["stars"], len(entry["via"]), entry["pushed_at"], self.now
        )
        return True

    def pop_batch(self, size: int) -> list[dict[str, Any]]:
        ordered = sorted(self.items.values(), key=lambda e: (-float(e.get("priority", 0)), e["id"]))
        batch = ordered[:size]
        for entry in batch:
            self.items.pop(str(entry["id"]).lower(), None)
        return batch

    def push_back(self, entries: list[dict[str, Any]]) -> None:
        for entry in entries:
            self.items[str(entry["id"]).lower()] = entry

    def __len__(self) -> int:
        return len(self.items)
