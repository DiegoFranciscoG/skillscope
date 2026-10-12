"""Analyzed repositories cached by commit (kept in the Actions cache, never published).

Each record holds the latest public metadata plus the content analysis of the last analyzed
commit. Unchanged repositories are never re-analyzed: a build only loads these small records
and recomputes the parts that depend on time or on other repositories.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from analyzer.model import ANALYZER_VERSION, RepoAnalysis
from pipeline.clock import iso
from pipeline.jsonio import read_json, write_json
from pipeline.models import RepoMeta

RECORD_VERSION = 1


def _filename(repo_id: str) -> str:
    owner, _, name = repo_id.lower().partition("/")
    return f"{owner}__{name}.json"


@dataclass(slots=True)
class CatalogRecord:
    meta: RepoMeta
    analysis: RepoAnalysis
    analyzed_oid: str | None
    analyzed_at: str | None
    first_seen: str | None


class CatalogStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path(self, repo_id: str) -> Path:
        return self.directory / _filename(repo_id)

    def put(self, analysis: RepoAnalysis, *, now: datetime, first_seen: str | None = None) -> None:
        previous = read_json(self.path(analysis.id)) or {}
        record = {
            "schema_version": RECORD_VERSION,
            "meta": _meta_dict(analysis.meta),
            "analyzed_oid": analysis.meta.head_oid,
            "analyzed_at": iso(now),
            "first_seen": previous.get("first_seen") or first_seen or iso(now),
            "analysis": analysis.to_dict(),
        }
        write_json(self.path(analysis.id), record)

    def update_meta(self, meta: RepoMeta) -> bool:
        data = read_json(self.path(meta.id))
        if not data:
            return False
        data["meta"] = _meta_dict(meta)
        write_json(self.path(meta.id), data)
        return True

    def needs_reanalysis(self, repo_id: str) -> bool:
        data = read_json(self.path(repo_id)) or {}
        version = int((data.get("analysis") or {}).get("analyzer_version", 0))
        return version != ANALYZER_VERSION

    def delete(self, repo_id: str) -> None:
        self.path(repo_id).unlink(missing_ok=True)

    def get(self, repo_id: str) -> CatalogRecord | None:
        data = read_json(self.path(repo_id))
        return _record(data) if data else None

    def __iter__(self) -> Iterator[CatalogRecord]:
        if not self.directory.exists():
            return
        for path in sorted(self.directory.glob("*.json")):
            data = read_json(path)
            if data:
                yield _record(data)


def _meta_dict(meta: RepoMeta) -> dict[str, Any]:
    return {k: getattr(meta, k) for k in RepoMeta.__dataclass_fields__}


def _record(data: dict[str, Any]) -> CatalogRecord:
    meta = RepoMeta.from_dict(data["meta"])
    return CatalogRecord(
        meta=meta,
        analysis=RepoAnalysis.from_dict(meta, data["analysis"]),
        analyzed_oid=data.get("analyzed_oid"),
        analyzed_at=data.get("analyzed_at"),
        first_seen=data.get("first_seen"),
    )
