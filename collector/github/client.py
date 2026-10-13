"""Thin GitHub API wrapper on top of ``HttpClient``.

Every call names the rate-limit resource it spends (core, search, code_search, graphql) so
each one gets its own budget, as the API itself does.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from collector.budget import Budget
from collector.http import HttpClient, RequestFailedError
from pipeline.clock import iso, parse_iso
from pipeline.config import Budgets
from pipeline.models import RepoMeta, TreeEntry

log = logging.getLogger("skillscope.github")

API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"
API_VERSION = "2026-03-10"
SOURCE = "github"


@dataclass(slots=True)
class GitHubBudgets:
    core: Budget
    search: Budget
    code_search: Budget
    graphql: Budget

    @classmethod
    def from_settings(cls, budgets: Budgets) -> GitHubBudgets:
        return cls(
            core=Budget("github.core", budgets.rest),
            search=Budget("github.search", budgets.search, min_interval=2.1),
            code_search=Budget("github.code_search", budgets.code_search, min_interval=6.5),
            graphql=Budget("github.graphql", budgets.graphql),
        )

    def all(self) -> dict[str, Budget]:
        return {
            "core": self.core,
            "search": self.search,
            "code_search": self.code_search,
            "graphql": self.graphql,
        }


@dataclass(slots=True)
class SearchPage:
    total_count: int
    incomplete: bool
    items: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class Tree:
    entries: list[TreeEntry]
    truncated: bool


META_FIELDS = """
  nameWithOwner name owner { login } url description isArchived isFork isTemplate
  stargazerCount forkCount pushedAt createdAt
  licenseInfo { spdxId }
  repositoryTopics(first: 20) { nodes { topic { name } } }
  openIssues: issues(states: OPEN) { totalCount }
  closedIssues: issues(states: CLOSED) { totalCount }
  releases(first: 1, orderBy: {field: CREATED_AT, direction: DESC}) { nodes { publishedAt } }
  defaultBranchRef {
    name
    target {
      ... on Commit {
        oid committedDate
        statusCheckRollup { state }
        history(since: $since) { totalCount }
      }
    }
  }
"""


def meta_from_graphql(node: dict[str, Any]) -> RepoMeta:
    branch = node.get("defaultBranchRef") or {}
    target = branch.get("target") or {}
    rollup = target.get("statusCheckRollup") or {}
    releases = (node.get("releases") or {}).get("nodes") or []
    topics = [
        t["topic"]["name"]
        for t in (node.get("repositoryTopics") or {}).get("nodes") or []
        if t and t.get("topic")
    ]
    license_info = node.get("licenseInfo") or {}
    owner, _, name = str(node["nameWithOwner"]).partition("/")
    return RepoMeta(
        id=str(node["nameWithOwner"]),
        owner=owner,
        name=name,
        url=str(node.get("url") or f"https://github.com/{node['nameWithOwner']}"),
        description=str(node.get("description") or ""),
        stars=int(node.get("stargazerCount") or 0),
        forks=int(node.get("forkCount") or 0),
        open_issues=int((node.get("openIssues") or {}).get("totalCount") or 0),
        closed_issues=int((node.get("closedIssues") or {}).get("totalCount") or 0),
        pushed_at=node.get("pushedAt"),
        created_at=node.get("createdAt"),
        last_commit_at=target.get("committedDate"),
        commits_30d=int((target.get("history") or {}).get("totalCount") or 0),
        archived=bool(node.get("isArchived")),
        is_fork=bool(node.get("isFork")),
        is_template=bool(node.get("isTemplate")),
        license=license_info.get("spdxId"),
        topics=topics,
        default_branch=str(branch.get("name") or "main"),
        head_oid=target.get("oid"),
        ci_state=rollup.get("state"),
        latest_release_at=releases[0].get("publishedAt") if releases and releases[0] else None,
    )


class GitHubClient:
    def __init__(self, http: HttpClient, token: str, budgets: GitHubBudgets) -> None:
        self.http = http
        self.budgets = budgets
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "skillscope-indexer",
        }

    # -- pre-flight -------------------------------------------------------------------------
    def preflight(self) -> dict[str, Any]:
        """Read the real remaining quota (free call) and cap every budget below the reserve."""
        probe = Budget("github.rate_limit", 1)
        result = self.http.get(
            f"{API}/rate_limit",
            source=SOURCE,
            budget=probe,
            headers=self._headers,
            conditional=False,
        )
        resources: dict[str, Any] = (result.data or {}).get("resources", {})
        for name, budget in self.budgets.all().items():
            info = resources.get(name)
            if isinstance(info, dict) and "remaining" in info and "limit" in info:
                budget.cap(int(info["remaining"]), int(info["limit"]))
        return resources

    # -- REST -------------------------------------------------------------------------------
    def search_repositories(self, query: str, *, page: int, sort: str = "stars") -> SearchPage:
        result = self.http.get(
            f"{API}/search/repositories",
            source=SOURCE,
            budget=self.budgets.search,
            params={"q": query, "sort": sort, "order": "desc", "per_page": 100, "page": page},
            headers=self._headers,
            free_on_304=True,
        )
        data = result.data or {}
        return SearchPage(
            total_count=int(data.get("total_count", 0)),
            incomplete=bool(data.get("incomplete_results", False)),
            items=list(data.get("items", [])),
        )

    def search_code(self, query: str, *, page: int) -> SearchPage:
        result = self.http.get(
            f"{API}/search/code",
            source=SOURCE,
            budget=self.budgets.code_search,
            params={"q": query, "per_page": 100, "page": page},
            headers=self._headers,
            free_on_304=True,
        )
        data = result.data or {}
        return SearchPage(
            total_count=int(data.get("total_count", 0)),
            incomplete=bool(data.get("incomplete_results", False)),
            items=list(data.get("items", [])),
        )

    def tree(self, repo_id: str, sha: str) -> Tree:
        result = self.http.get(
            f"{API}/repos/{repo_id}/git/trees/{sha}",
            source=SOURCE,
            budget=self.budgets.core,
            params={"recursive": "1"},
            headers=self._headers,
            free_on_304=True,
        )
        data = result.data or {}
        entries = [
            TreeEntry(path=str(item["path"]), size=int(item.get("size") or 0))
            for item in data.get("tree", [])
            if item.get("type") == "blob"
        ]
        return Tree(entries=entries, truncated=bool(data.get("truncated", False)))

    def star_history(self, repo_id: str, weeks: int = 3) -> list[dict[str, Any]]:
        """Stars per day for the last ``weeks`` weeks (aggregate counts, no user data)."""
        result = self.http.get(
            f"{API}/repos/{repo_id}/stargazers/history",
            source=SOURCE,
            budget=self.budgets.core,
            params={"per_page": weeks},
            headers=self._headers,
            free_on_304=True,
        )
        return list(result.data or [])

    def issues(self, repo_id: str, *, label: str, state: str = "all") -> list[dict[str, Any]]:
        result = self.http.get(
            f"{API}/repos/{repo_id}/issues",
            source=SOURCE,
            budget=self.budgets.core,
            params={"labels": label, "state": state, "per_page": 100},
            headers=self._headers,
            free_on_304=True,
        )
        return list(result.data or [])

    # -- GraphQL ----------------------------------------------------------------------------
    def graphql(self, query: str, variables: dict[str, Any], *, cost_hint: int = 1) -> Any:
        result = self.http.post(
            GRAPHQL,
            source=SOURCE,
            budget=self.budgets.graphql,
            json_body={"query": query, "variables": variables},
            headers=self._headers,
            cost=cost_hint,
            retry_server_errors=False,  # callers split the batch instead of repeating it
        )
        payload = result.data or {}
        data = payload.get("data")
        if data is None:
            errors = payload.get("errors") or []
            message = errors[0].get("message", "unknown") if errors else "empty response"
            raise RequestFailedError(SOURCE, result.status, f"graphql: {message}")
        cost = ((data.get("rateLimit") or {}).get("cost")) or cost_hint
        extra = int(cost) - cost_hint
        if extra > 0:
            self.budgets.graphql.used += extra
        return data

    def repo_meta(self, repo_ids: list[str], now: datetime) -> dict[str, RepoMeta]:
        """Metadata for up to 40 repos in one GraphQL call (about 1–3 points)."""
        if not repo_ids:
            return {}
        decl = ["$since: GitTimestamp!"]
        parts = ["rateLimit { cost remaining }"]
        variables: dict[str, Any] = {"since": iso(now - timedelta(days=30))}
        for i, repo_id in enumerate(repo_ids):
            owner, _, name = repo_id.partition("/")
            decl += [f"$o{i}: String!", f"$n{i}: String!"]
            variables[f"o{i}"] = owner
            variables[f"n{i}"] = name
            parts.append(f"r{i}: repository(owner: $o{i}, name: $n{i}) {{ {META_FIELDS} }}")
        query = f"query({', '.join(decl)}) {{ {' '.join(parts)} }}"
        data = self.graphql(query, variables)
        out: dict[str, RepoMeta] = {}
        for i, repo_id in enumerate(repo_ids):
            node = data.get(f"r{i}")
            if node:
                out[repo_id.lower()] = meta_from_graphql(node)
        return out

    def blobs(self, requests: list[tuple[str, str, str]]) -> dict[tuple[str, str], str]:
        """Text of files given as (repo_id, commit_oid, path); binary or huge blobs are skipped."""
        if not requests:
            return {}
        decl: list[str] = []
        parts = ["rateLimit { cost remaining }"]
        variables: dict[str, Any] = {}
        for i, (repo_id, oid, path) in enumerate(requests):
            owner, _, name = repo_id.partition("/")
            decl += [f"$o{i}: String!", f"$n{i}: String!", f"$e{i}: String!"]
            variables.update({f"o{i}": owner, f"n{i}": name, f"e{i}": f"{oid}:{path}"})
            parts.append(
                f"f{i}: repository(owner: $o{i}, name: $n{i}) "
                f"{{ object(expression: $e{i}) {{ ... on Blob {{ text isBinary isTruncated }} }} }}"
            )
        query = f"query({', '.join(decl)}) {{ {' '.join(parts)} }}"
        data = self.graphql(query, variables)
        out: dict[tuple[str, str], str] = {}
        for i, (repo_id, _oid, path) in enumerate(requests):
            obj = ((data.get(f"f{i}") or {}).get("object")) or {}
            text = obj.get("text")
            if isinstance(text, str) and not obj.get("isBinary"):
                out[(repo_id.lower(), path)] = text
        return out


def is_recent(value: str | None, now: datetime, days: int) -> bool:
    moment = parse_iso(value)
    return moment is not None and (now - moment) <= timedelta(days=days)
