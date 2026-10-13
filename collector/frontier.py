"""Queue of repositories waiting to be analyzed, ordered by a simple priority."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from collector.state import StateStore
from pipeline.clock import days_between, iso, parse_iso

DESCRIPTION_CHARS = 300
MAX_TOPICS = 8
SUGGESTION_BOOST = 100.0  # a visitor asked for it: analyze before anything found by search
DONE = frozenset({"artifact", "internal", "unavailable", "opted_out", "gone"})


def _worth_queueing(known: dict[str, Any], pushed_at: str | None) -> bool:
    """A repository analyzed before is queued again only if it got commits since then."""
    status = known.get("status")
    if status in DONE:
        return False
    if status == "no_artifact":
        analyzed = known.get("analyzed_at") or ""
        return bool(pushed_at) and str(pushed_at) > str(analyzed)
    return True


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
        description: str | None = None,
        topics: list[str] | None = None,
        language: str | None = None,
    ) -> bool:
        """Queue a candidate. Returns True only when it was not queued before.

        Repositories already analyzed are skipped: indexed ones are refreshed by the enricher
        every build, and those without artifacts come back only after a newer push. What the
        search API says about a candidate (description, topics, language) is kept so visitors
        can search the queue before it is analyzed.
        """
        key = repo_id.lower()
        if excluded and key in excluded:
            return False
        known = self.state.known_repo(repo_id)
        if known and not _worth_queueing(known, pushed_at):
            return False
        entry = self.items.get(key)
        created = entry is None
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
        if description:
            entry["description"] = " ".join(description.split())[:DESCRIPTION_CHARS]
        if topics:
            entry["topics"] = [str(t) for t in topics[:MAX_TOPICS]]
        if language:
            entry["language"] = str(language)[:40]
        entry["priority"] = priority(
            entry["stars"], len(entry["via"]), entry["pushed_at"], self.now
        ) + (SUGGESTION_BOOST if "suggestion" in entry["via"] else 0.0)
        return created

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
