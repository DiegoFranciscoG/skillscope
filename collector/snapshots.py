"""One JSON file per analyzed repository (kept in the Actions cache, never published)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from pipeline.jsonio import read_json, write_json
from pipeline.models import RepoSnapshot


def _filename(repo_id: str) -> str:
    owner, _, name = repo_id.lower().partition("/")
    return f"{owner}__{name}.json"


class SnapshotStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def save(self, snapshot: RepoSnapshot) -> None:
        write_json(self.directory / _filename(snapshot.id), snapshot.to_dict())

    def load(self, repo_id: str) -> RepoSnapshot | None:
        data = read_json(self.directory / _filename(repo_id))
        return RepoSnapshot.from_dict(data) if data else None

    def delete(self, repo_id: str) -> None:
        (self.directory / _filename(repo_id)).unlink(missing_ok=True)

    def __iter__(self) -> Iterator[RepoSnapshot]:
        if not self.directory.exists():
            return
        for path in sorted(self.directory.glob("*.json")):
            data = read_json(path)
            if data:
                yield RepoSnapshot.from_dict(data)
