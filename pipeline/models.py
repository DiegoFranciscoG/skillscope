"""Data exchanged between collector, analyzer and indexer.

A ``RepoSnapshot`` is everything the collector knows about one repository at one commit:
public metadata, the list of files and the text of the few files the analyzer needs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = 1


@dataclass(slots=True)
class RepoMeta:
    id: str
    owner: str
    name: str
    url: str
    description: str = ""
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    closed_issues: int = 0
    pushed_at: str | None = None
    created_at: str | None = None
    last_commit_at: str | None = None
    commits_30d: int = 0
    archived: bool = False
    is_fork: bool = False
    is_template: bool = False
    license: str | None = None
    topics: list[str] = field(default_factory=list)
    default_branch: str = "main"
    head_oid: str | None = None
    ci_state: str | None = None
    latest_release_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepoMeta:
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        return cls(**known)


@dataclass(slots=True)
class TreeEntry:
    path: str
    size: int


@dataclass(slots=True)
class RepoSnapshot:
    meta: RepoMeta
    tree: list[TreeEntry] = field(default_factory=list)
    tree_truncated: bool = False
    files: dict[str, str] = field(default_factory=dict)
    via: list[str] = field(default_factory=list)
    npm_package: str | None = None
    npm_downloads: int | None = None
    fetched_at: str | None = None
    sample: bool = False

    @property
    def id(self) -> str:
        return self.meta.id

    def paths(self) -> list[str]:
        return [e.path for e in self.tree]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tree"] = [[e.path, e.size] for e in self.tree]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepoSnapshot:
        tree = [TreeEntry(path=str(p), size=int(s)) for p, s in data.get("tree", [])]
        return cls(
            meta=RepoMeta.from_dict(data["meta"]),
            tree=tree,
            tree_truncated=bool(data.get("tree_truncated", False)),
            files={str(k): str(v) for k, v in data.get("files", {}).items()},
            via=[str(v) for v in data.get("via", [])],
            npm_package=data.get("npm_package"),
            npm_downloads=data.get("npm_downloads"),
            fetched_at=data.get("fetched_at"),
            sample=bool(data.get("sample", False)),
        )


@dataclass(slots=True)
class Mention:
    """One public post that links ``github.com/<repo_id>``. Only counts are kept."""

    source: str
    key_hash: str
    repo_id: str
    day: str
    engagement: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Mention:
        return cls(
            source=str(data["source"]),
            key_hash=str(data["key_hash"]),
            repo_id=str(data["repo_id"]),
            day=str(data["day"]),
            engagement=int(data.get("engagement", 0)),
        )


@dataclass(slots=True)
class DemandItem:
    """A public question that shows unmet demand.

    ``title``/``url``/``author`` are only filled for sources whose license allows showing
    them with attribution (Stack Exchange, CC BY-SA). Aggregated sources use ``count``.
    """

    source: str
    id: str
    created_at: str
    text: str
    answered: bool = False
    tags: list[str] = field(default_factory=list)
    title: str | None = None
    url: str | None = None
    author: str | None = None
    author_url: str | None = None
    count: int = 1

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DemandItem:
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        return cls(**known)
