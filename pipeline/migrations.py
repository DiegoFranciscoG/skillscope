"""Versioned migrations for the JSON state files (the project has no database).

Each function upgrades a document by exactly one version. ``migrate`` applies them in order,
so an old cache restored from a previous build is always readable.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

STATE_VERSION = 1

Doc = dict[str, Any]


def _v0_to_v1(doc: Doc) -> Doc:
    """v0 (no version field) kept ETags under "etags"; v1 renames it to "resources"."""
    upgraded = dict(doc)
    upgraded["resources"] = upgraded.pop("etags", upgraded.get("resources", {}))
    upgraded.setdefault("cursors", {})
    upgraded.setdefault("schedule", {})
    upgraded.setdefault("repos", {})
    upgraded.setdefault("frontier", [])
    upgraded["schema_version"] = 1
    return upgraded


_STEPS: dict[int, Callable[[Doc], Doc]] = {0: _v0_to_v1}


def empty_state() -> Doc:
    return {
        "schema_version": STATE_VERSION,
        "resources": {},
        "cursors": {},
        "schedule": {},
        "repos": {},
        "frontier": [],
        "last_build": None,
    }


def migrate(doc: Doc | None) -> Doc:
    if not doc:
        return empty_state()
    version = int(doc.get("schema_version", 0))
    if version > STATE_VERSION:
        raise ValueError(f"state schema {version} is newer than supported {STATE_VERSION}")
    while version < STATE_VERSION:
        doc = _STEPS[version](doc)
        version = int(doc["schema_version"])
    return doc
