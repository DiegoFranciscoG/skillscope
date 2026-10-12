"""Time series and events that survive between builds (Actions cache).

- Daily stars, forks and commits per repository (90 days kept, 60 published).
- Mention events: source, hashed post id, repository, day, engagement (180 days).
- Demand items (Stack Exchange questions for a year; Reddit only as counts).
- npm monthly downloads per package (refreshed every 24 h).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pipeline.clock import iso, parse_iso
from pipeline.jsonio import read_json, write_json
from pipeline.models import DemandItem, Mention

SERIES_DAYS = 90
MENTION_DAYS = 180
DEMAND_DAYS = 365
NPM_REFRESH_HOURS = 24


def _empty() -> dict[str, Any]:
    return {"schema_version": 1, "repos": {}, "mentions": {}, "demand": {}, "npm": {}}


class SignalStore:
    def __init__(self, directory: Path) -> None:
        self.path = directory / "signals.json"
        self.data: dict[str, Any] = read_json(self.path) or _empty()

    def save(self) -> None:
        write_json(self.path, self.data)

    # -- repository series ------------------------------------------------------------------
    def record_repo(self, repo_id: str, day: str, *, stars: int, forks: int, commits: int) -> None:
        entry = self.data["repos"].setdefault(
            repo_id.lower(), {"id": repo_id, "stars": {}, "forks": {}, "commits": {}}
        )
        entry["id"] = repo_id
        entry["stars"][day] = stars
        entry["forks"][day] = forks
        entry["commits"][day] = commits

    def series(self, repo_id: str, field: str, days: list[str]) -> list[int | None]:
        entry = self.data["repos"].get(repo_id.lower()) or {}
        values: dict[str, int] = entry.get(field) or {}
        return [values.get(day) for day in days]

    def value_on_or_before(self, repo_id: str, field: str, day: str) -> int | None:
        """Most recent value recorded on ``day`` or earlier (oldest available otherwise)."""
        entry = self.data["repos"].get(repo_id.lower()) or {}
        values: dict[str, int] = entry.get(field) or {}
        if not values:
            return None
        candidates = [d for d in values if d <= day]
        return values[max(candidates)] if candidates else values[min(values)]

    # -- mentions -----------------------------------------------------------------------------
    def add_mentions(self, mentions: list[Mention]) -> int:
        store: dict[str, Any] = self.data["mentions"]
        added = 0
        for mention in mentions:
            if mention.key_hash not in store:
                added += 1
            store[mention.key_hash] = {
                "source": mention.source,
                "repo_id": mention.repo_id,
                "day": mention.day,
                "engagement": mention.engagement,
            }
        return added

    def mentions_by_repo(self) -> dict[str, list[Mention]]:
        out: dict[str, list[Mention]] = {}
        for key, value in self.data["mentions"].items():
            mention = Mention.from_dict({"key_hash": key, **value})
            out.setdefault(mention.repo_id.lower(), []).append(mention)
        return out

    # -- demand -------------------------------------------------------------------------------
    def add_demand(self, items: list[DemandItem]) -> int:
        store: dict[str, Any] = self.data["demand"]
        added = 0
        for item in items:
            key = f"{item.source}:{item.id}"
            if key not in store:
                added += 1
            store[key] = {k: getattr(item, k) for k in DemandItem.__dataclass_fields__}
        return added

    def demand(self) -> list[DemandItem]:
        return [DemandItem.from_dict(v) for v in self.data["demand"].values()]

    # -- npm ----------------------------------------------------------------------------------
    def npm_due(self, package: str, now: datetime) -> bool:
        entry = self.data["npm"].get(package)
        fetched = parse_iso(entry.get("fetched_at")) if entry else None
        return fetched is None or now - fetched >= timedelta(hours=NPM_REFRESH_HOURS)

    def set_npm(self, package: str, downloads: int | None, now: datetime) -> None:
        self.data["npm"][package] = {"downloads": downloads, "fetched_at": iso(now)}

    def npm_downloads(self, package: str | None) -> int | None:
        if not package:
            return None
        entry = self.data["npm"].get(package)
        return None if entry is None else entry.get("downloads")

    # -- retention ----------------------------------------------------------------------------
    def prune(self, now: datetime, keep_repos: set[str] | None = None) -> None:
        series_cut = (now - timedelta(days=SERIES_DAYS)).strftime("%Y-%m-%d")
        for repo_key in list(self.data["repos"]):
            if keep_repos is not None and repo_key not in keep_repos:
                del self.data["repos"][repo_key]
                continue
            entry = self.data["repos"][repo_key]
            for field in ("stars", "forks", "commits"):
                entry[field] = {d: v for d, v in entry.get(field, {}).items() if d >= series_cut}
        mention_cut = (now - timedelta(days=MENTION_DAYS)).strftime("%Y-%m-%d")
        self.data["mentions"] = {
            k: v for k, v in self.data["mentions"].items() if v.get("day", "") >= mention_cut
        }
        demand_cut = iso(now - timedelta(days=DEMAND_DAYS))
        self.data["demand"] = {
            k: v for k, v in self.data["demand"].items() if v.get("created_at", "") >= demand_cut
        }
