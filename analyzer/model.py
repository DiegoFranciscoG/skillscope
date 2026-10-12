"""Results of analyzing one repository snapshot.

``RepoAnalysis`` keeps only what is derived from the repository content at one commit, so it
can be cached by commit and reused by every later build. Time-dependent text (activity) and
cross-repository data (collections, scores) are added at index time.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from pipeline.models import RepoMeta

ANALYZER_VERSION = 1
MAX_INDEX_TEXT = 8000


@dataclass(slots=True)
class Artifact:
    # skill | plugin_manifest | marketplace_manifest | agent | command | hook_config | mcp_config
    kind: str
    path: str
    name: str
    valid: bool
    issues: list[str] = field(default_factory=list)
    description: str = ""  # internal: used for classification, never published verbatim
    lines: int = 0
    tools: list[str] = field(default_factory=list)
    has_when: bool = False
    loads_in_claude_code: bool = True

    def public(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": self.path,
            "name": self.name,
            "valid": self.valid,
            "issues": self.issues,
        }


@dataclass(slots=True)
class Evidence:
    path: str
    line: int
    snippet: str


@dataclass(slots=True)
class RiskFlag:
    id: str
    severity: str
    penalty: int
    title: str
    why: str
    evidence: list[Evidence] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RiskFlag:
        return cls(
            id=data["id"],
            severity=data["severity"],
            penalty=int(data["penalty"]),
            title=data["title"],
            why=data["why"],
            evidence=[Evidence(**e) for e in data.get("evidence", [])],
        )


@dataclass(slots=True)
class InstallStep:
    label: str
    command: str


@dataclass(slots=True)
class Install:
    kind: str  # marketplace | plugin_dir | skill_copy | mcp | template | list | manual
    steps: list[InstallStep] = field(default_factory=list)
    note: str = ""
    one_liner: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Install:
        return cls(
            kind=data["kind"],
            steps=[InstallStep(**s) for s in data.get("steps", [])],
            note=data.get("note", ""),
            one_liner=data.get("one_liner"),
        )


@dataclass(slots=True)
class MarketplaceEntry:
    name: str
    source_type: str
    repo: str | None  # referenced GitHub repo id for external sources
    pinned: bool


@dataclass(slots=True)
class RepoAnalysis:
    meta: RepoMeta
    sample: bool
    type: str
    category: str
    categories: list[str]
    cause: str
    category_terms: list[str]
    artifacts: list[Artifact]
    counts: dict[str, int]
    tools: list[str]
    readme_lang: str
    keywords: list[str]
    marketplace_name: str | None
    marketplace_entries: list[MarketplaceEntry]
    list_links: list[str]
    install: Install
    risks: list[RiskFlag]
    facts: dict[str, Any]
    index_text: str  # internal text for search vectors (names, descriptions, topics)
    summary_lead: str
    summary_facts: list[str]
    included: list[str]
    when: list[str] = field(default_factory=list)
    npm_package: str | None = None
    npm_downloads: int | None = None
    analyzer_version: int = ANALYZER_VERSION
    source_text: str = ""  # README + descriptions, only kept in memory for the copy guard

    @property
    def id(self) -> str:
        return self.meta.id

    @property
    def risk_penalty(self) -> int:
        return min(25, sum(f.penalty for f in self.risks))

    def summary(self, now: datetime) -> str:
        from analyzer.summary import activity_phrase, compose_summary

        activity = activity_phrase(
            self.meta.last_commit_at or self.meta.pushed_at, self.meta.archived, now
        )
        return compose_summary(self.summary_lead, self.summary_facts, activity)

    def what(self, now: datetime) -> str:
        text = self.summary(now)
        if self.included:
            suffix = "…" if len(self.included) == 5 else "."
            text += " Incluye: " + ", ".join(self.included) + suffix
        return text

    def to_dict(self) -> dict[str, Any]:
        return {
            "analyzer_version": self.analyzer_version,
            "sample": self.sample,
            "type": self.type,
            "category": self.category,
            "categories": self.categories,
            "cause": self.cause,
            "category_terms": self.category_terms,
            "artifacts": [asdict(a) for a in self.artifacts],
            "counts": self.counts,
            "tools": self.tools,
            "readme_lang": self.readme_lang,
            "keywords": self.keywords,
            "marketplace_name": self.marketplace_name,
            "marketplace_entries": [asdict(e) for e in self.marketplace_entries],
            "list_links": self.list_links,
            "install": self.install.to_dict(),
            "risks": [r.to_dict() for r in self.risks],
            "facts": self.facts,
            "index_text": self.index_text[:MAX_INDEX_TEXT],
            "summary_lead": self.summary_lead,
            "summary_facts": self.summary_facts,
            "included": self.included,
            "when": self.when,
            "npm_package": self.npm_package,
            "npm_downloads": self.npm_downloads,
        }

    @classmethod
    def from_dict(cls, meta: RepoMeta, data: dict[str, Any]) -> RepoAnalysis:
        return cls(
            meta=meta,
            sample=bool(data.get("sample", False)),
            type=data["type"],
            category=data["category"],
            categories=list(data.get("categories", [])),
            cause=data["cause"],
            category_terms=list(data.get("category_terms", [])),
            artifacts=[Artifact(**a) for a in data.get("artifacts", [])],
            counts=dict(data.get("counts", {})),
            tools=list(data.get("tools", [])),
            readme_lang=data.get("readme_lang", "und"),
            keywords=list(data.get("keywords", [])),
            marketplace_name=data.get("marketplace_name"),
            marketplace_entries=[
                MarketplaceEntry(**e) for e in data.get("marketplace_entries", [])
            ],
            list_links=list(data.get("list_links", [])),
            install=Install.from_dict(data["install"]),
            risks=[RiskFlag.from_dict(r) for r in data.get("risks", [])],
            facts=dict(data.get("facts", {})),
            index_text=data.get("index_text", ""),
            summary_lead=data.get("summary_lead", ""),
            summary_facts=list(data.get("summary_facts", [])),
            included=list(data.get("included", [])),
            when=list(data.get("when", [])),
            npm_package=data.get("npm_package"),
            npm_downloads=data.get("npm_downloads"),
            analyzer_version=int(data.get("analyzer_version", 0)),
        )
