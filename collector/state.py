"""Persistent collector state: ETags, cursors, per-source schedule and per-repo progress."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

from pipeline.clock import Clock, iso, parse_iso
from pipeline.jsonio import read_json, write_json
from pipeline.migrations import migrate


class StateStore:
    def __init__(self, path: Path, clock: Clock) -> None:
        self.path = path
        self.clock = clock
        self.data: dict[str, Any] = migrate(read_json(path))

    def save(self) -> None:
        write_json(self.path, self.data)

    # -- HTTP cache -------------------------------------------------------------------------
    def resource(self, key: str) -> dict[str, Any] | None:
        value = self.data["resources"].get(key)
        return value if isinstance(value, dict) else None

    def remember(self, key: str, *, etag: str | None, last_modified: str | None, sha: str) -> None:
        self.data["resources"][key] = {
            "etag": etag,
            "last_modified": last_modified,
            "body_sha256": sha,
            "fetched_at": iso(self.clock.now()),
        }

    def referenced_objects(self) -> set[str]:
        return {
            str(v["body_sha256"])
            for v in self.data["resources"].values()
            if isinstance(v, dict) and v.get("body_sha256")
        }

    # -- cursors ----------------------------------------------------------------------------
    def cursor(self, name: str) -> dict[str, Any]:
        cursors: dict[str, Any] = self.data["cursors"]
        return cast(dict[str, Any], cursors.setdefault(name, {}))

    # -- per-source cadence -----------------------------------------------------------------
    def is_due(self, source: str) -> bool:
        next_at = parse_iso(self.data["schedule"].get(source))
        return next_at is None or self.clock.now() >= next_at

    def schedule_next(self, source: str, minutes: int) -> None:
        when: datetime = self.clock.now() + timedelta(minutes=minutes)
        self.data["schedule"][source] = iso(when)

    # -- repositories -----------------------------------------------------------------------
    def repo(self, repo_id: str) -> dict[str, Any]:
        repos: dict[str, Any] = self.data["repos"]
        key = repo_id.lower()
        entry = repos.get(key)
        if entry is None:
            entry = {"id": repo_id, "first_seen": iso(self.clock.now()), "status": "candidate"}
            repos[key] = entry
        return cast(dict[str, Any], entry)

    def known_repo(self, repo_id: str) -> dict[str, Any] | None:
        value = self.data["repos"].get(repo_id.lower())
        return value if isinstance(value, dict) else None

    def repos(self) -> dict[str, dict[str, Any]]:
        return dict(self.data["repos"])
