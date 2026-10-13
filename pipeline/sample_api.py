"""In-memory imitation of the GitHub and social APIs, backed by ``data/samples``.

It powers the offline build (``docker compose`` and CI) and the integration tests, so both
run the real collector code paths without network access or tokens. It also enforces rate
limits like GitHub does, which is how the tests prove the collector never exceeds them.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx

from pipeline.clock import Clock, iso, parse_iso

_REL = re.compile(r"^-(\d+)d$")
_TREE_PATH = re.compile(r"^/repos/([^/]+)/([^/]+)/git/trees/([0-9a-f]+)$")
_ISSUES_PATH = re.compile(r"^/repos/([^/]+)/([^/]+)/issues$")

DEFAULT_LIMITS = {"core": 5000, "search": 30, "code_search": 10, "graphql": 5000}


def resolve_dates(value: Any, now: datetime) -> Any:
    """Turn relative offsets like "-3d" into ISO timestamps, recursively."""
    if isinstance(value, str):
        match = _REL.match(value)
        if match:
            return iso(now - timedelta(days=int(match.group(1))))
        return value
    if isinstance(value, list):
        return [resolve_dates(v, now) for v in value]
    if isinstance(value, dict):
        return {k: resolve_dates(v, now) for k, v in value.items()}
    return value


def _epoch(value: str) -> int:
    moment = parse_iso(value)
    return int(moment.timestamp()) if moment else 0


def load_sample_repos(samples_dir: Path, now: datetime) -> list[dict[str, Any]]:
    repos = []
    for path in sorted((samples_dir / "repos").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        # The fake commit id depends on the *relative* date, so it is stable across builds.
        seed = f"{data['meta']['id']}|{data['meta'].get('pushed_at')}"
        resolved = resolve_dates(data, now)
        resolved["oid_seed"] = seed
        repos.append(resolved)
    return repos


def head_oid(repo: dict[str, Any]) -> str:
    seed = str(repo.get("oid_seed") or f"{repo['meta']['id']}|{repo['meta']['pushed_at']}")
    return hashlib.sha1(seed.encode(), usedforsecurity=False).hexdigest()


class SampleApi:
    def __init__(
        self,
        samples_dir: Path,
        clock: Clock,
        *,
        limits: dict[str, int] | None = None,
        issues: list[dict[str, Any]] | None = None,
        fail_hosts: set[str] | None = None,
    ) -> None:
        self.clock = clock
        self.now = clock.now()
        self.repos = load_sample_repos(samples_dir, self.now)
        self.by_id = {r["meta"]["id"].lower(): r for r in self.repos}
        social_dir = samples_dir / "social"
        self.social = {
            p.stem: resolve_dates(json.loads(p.read_text(encoding="utf-8")), self.now)
            for p in sorted(social_dir.glob("*.json"))
        }
        self.limits = dict(DEFAULT_LIMITS | (limits or {}))
        self.remaining = dict(self.limits)
        self.calls: Counter[str] = Counter()
        self.overruns: Counter[str] = Counter()
        self.issues = issues or []
        self.fail_hosts = fail_hosts or set()

    # -- plumbing ---------------------------------------------------------------------------
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def _limited(self, resource: str, payload: Any, status: int = 200) -> httpx.Response:
        self.calls[resource] += 1
        if self.remaining[resource] <= 0:
            self.overruns[resource] += 1
            return httpx.Response(
                403,
                json={"message": "API rate limit exceeded"},
                headers=self._rate_headers(resource),
            )
        self.remaining[resource] -= 1
        return httpx.Response(status, json=payload, headers=self._rate_headers(resource))

    def _rate_headers(self, resource: str) -> dict[str, str]:
        reset = int((self.clock.now() + timedelta(hours=1)).timestamp())
        return {
            "x-ratelimit-limit": str(self.limits[resource]),
            "x-ratelimit-remaining": str(max(0, self.remaining[resource])),
            "x-ratelimit-reset": str(reset),
            "x-ratelimit-resource": resource,
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host in self.fail_hosts:
            return httpx.Response(503, json={"error": "sample outage"})
        routes: dict[str, Callable[[httpx.Request], httpx.Response]] = {
            "api.github.com": self._github,
            "hn.algolia.com": self._hackernews,
            "api.stackexchange.com": self._stackexchange,
            "dev.to": self._devto,
            "mastodon.social": self._mastodon,
            "hachyderm.io": self._mastodon,
            "fosstodon.org": self._mastodon,
            "infosec.exchange": self._mastodon,
            "mas.to": self._mastodon,
            "programming.dev": self._lemmy,
            "api.bsky.app": self._bluesky,
            "lemmy.world": self._lemmy,
            "api.npmjs.org": self._npm,
        }
        route = routes.get(host)
        if route is None:
            return httpx.Response(404, json={"message": "not in samples"})
        return route(request)

    # -- GitHub -----------------------------------------------------------------------------
    def _github(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/rate_limit":
            resources = {
                name: {
                    "limit": self.limits[name],
                    "remaining": self.remaining[name],
                    "reset": int((self.now + timedelta(hours=1)).timestamp()),
                }
                for name in self.limits
            }
            return httpx.Response(200, json={"resources": resources})
        if path == "/search/repositories":
            return self._limited("search", self._search_repos(request))
        if path == "/search/code":
            return self._limited("code_search", self._search_code(request))
        if path == "/graphql":
            return self._graphql(request)
        tree = _TREE_PATH.match(path)
        if tree:
            return self._tree(request, f"{tree.group(1)}/{tree.group(2)}")
        issues = _ISSUES_PATH.match(path)
        if issues:
            return self._limited("core", self.issues)
        return httpx.Response(404, json={"message": "Not Found"})

    def _query(self, request: httpx.Request) -> tuple[list[str], dict[str, str]]:
        q = unquote(request.url.params.get("q", ""))
        words: list[str] = []
        quals: dict[str, str] = {}
        for token in q.split():
            key, sep, value = token.partition(":")
            if sep and key in {"topic", "created", "pushed", "filename", "path", "size"}:
                quals[key] = value
            else:
                words.append(token.lower())
        return words, quals

    def _search_repos(self, request: httpx.Request) -> dict[str, Any]:
        words, quals = self._query(request)
        matches = []
        for repo in self.repos:
            meta = repo["meta"]
            topics = [t.lower() for t in meta["topics"]]
            if "topic" in quals and quals["topic"].lower() not in topics:
                continue
            haystack = " ".join([meta["name"], meta["description"], *topics]).lower()
            if any(w not in haystack for w in words):
                continue
            if "created" in quals:
                low, _, high = quals["created"].partition("..")
                created = meta["created_at"][:10]
                if not low <= created <= high:
                    continue
            if "pushed" in quals and meta["pushed_at"] < quals["pushed"].lstrip(">="):
                continue
            matches.append(meta)
        key = "pushed_at" if request.url.params.get("sort") == "updated" else "stars"
        matches.sort(key=lambda m: (m[key], m["id"]), reverse=True)
        per_page = int(request.url.params.get("per_page", 30))
        page = int(request.url.params.get("page", 1))
        chunk = matches[(page - 1) * per_page : page * per_page]
        return {
            "total_count": len(matches),
            "incomplete_results": False,
            "items": [
                {
                    "full_name": m["id"],
                    "stargazers_count": m["stars"],
                    "pushed_at": m["pushed_at"],
                    "fork": False,
                }
                for m in chunk
            ],
        }

    def _search_code(self, request: httpx.Request) -> dict[str, Any]:
        _words, quals = self._query(request)
        filename = quals.get("filename", "")
        folder = quals.get("path", "")
        low, _, high = quals.get("size", "0..10000000").partition("..")
        items = []
        for repo in self.repos:
            for path, size in repo["tree"]:
                base = path.rsplit("/", 1)[-1]
                if base != filename or (folder and f"{folder}/" not in f"/{path}"):
                    continue
                if not int(low) <= int(size) <= int(high):
                    continue
                items.append({"path": path, "repository": {"full_name": repo["meta"]["id"]}})
        per_page = int(request.url.params.get("per_page", 30))
        page = int(request.url.params.get("page", 1))
        return {
            "total_count": len(items),
            "incomplete_results": False,
            "items": items[(page - 1) * per_page : page * per_page],
        }

    def _tree(self, request: httpx.Request, repo_id: str) -> httpx.Response:
        repo = self.by_id.get(repo_id.lower())
        if repo is None:
            return httpx.Response(404, json={"message": "Not Found"})
        etag = f'W/"{head_oid(repo)}"'
        if request.headers.get("if-none-match") == etag:
            self.calls["core_304"] += 1
            return httpx.Response(304, headers={"etag": etag, **self._rate_headers("core")})
        payload = {
            "sha": head_oid(repo),
            "truncated": False,
            "tree": [{"path": p, "type": "blob", "size": s} for p, s in repo["tree"]],
        }
        response = self._limited("core", payload)
        response.headers["etag"] = etag
        return response

    def _graphql(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        variables: dict[str, Any] = body.get("variables") or {}
        data: dict[str, Any] = {"rateLimit": {"cost": 1, "remaining": self.remaining["graphql"]}}
        index = 0
        while f"o{index}" in variables:
            repo_id = f"{variables[f'o{index}']}/{variables[f'n{index}']}".lower()
            repo = self.by_id.get(repo_id)
            if f"e{index}" in variables:
                oid, _, path = str(variables[f"e{index}"]).partition(":")
                text = None
                if repo and oid == head_oid(repo):
                    text = repo["files"].get(path)
                obj = (
                    None
                    if text is None
                    else {"text": text, "isBinary": False, "isTruncated": False}
                )
                data[f"f{index}"] = {"object": obj} if repo else None
            else:
                data[f"r{index}"] = self._meta_node(repo) if repo else None
            index += 1
        return self._limited("graphql", {"data": data})

    def _meta_node(self, repo: dict[str, Any]) -> dict[str, Any]:
        meta = repo["meta"]
        return {
            "nameWithOwner": meta["id"],
            "name": meta["name"],
            "owner": {"login": meta["owner"]},
            "url": meta["url"],
            "description": meta["description"],
            "isArchived": meta["archived"],
            "isFork": False,
            "isTemplate": meta["is_template"],
            "stargazerCount": meta["stars"],
            "forkCount": meta["forks"],
            "pushedAt": meta["pushed_at"],
            "createdAt": meta["created_at"],
            "licenseInfo": {"spdxId": meta["license"]} if meta["license"] else None,
            "repositoryTopics": {"nodes": [{"topic": {"name": t}} for t in meta["topics"]]},
            "openIssues": {"totalCount": meta["open_issues"]},
            "closedIssues": {"totalCount": meta["closed_issues"]},
            "releases": {
                "nodes": [{"publishedAt": meta["latest_release_at"]}]
                if meta["latest_release_at"]
                else []
            },
            "defaultBranchRef": {
                "name": "main",
                "target": {
                    "oid": head_oid(repo),
                    "committedDate": meta["last_commit_at"],
                    "statusCheckRollup": {"state": meta["ci_state"]} if meta["ci_state"] else None,
                    "history": {"totalCount": meta["commits_30d"]},
                },
            },
        }

    # -- social -----------------------------------------------------------------------------
    def _hackernews(self, request: httpx.Request) -> httpx.Response:
        data = json.loads(json.dumps(self.social.get("hackernews", {"hits": []})))
        for hit in data.get("hits", []):
            hit["created_at_i"] = _epoch(hit["created_at_i"])
        return httpx.Response(200, json=data)

    def _stackexchange(self, request: httpx.Request) -> httpx.Response:
        data = json.loads(json.dumps(self.social.get("stackexchange", {"items": []})))
        for item in data.get("items", []):
            item["creation_date"] = _epoch(item["creation_date"])
        return httpx.Response(200, json=data)

    def _devto(self, request: httpx.Request) -> httpx.Response:
        articles = self.social.get("devto", {}).get("articles", [])
        path = request.url.path
        if path == "/api/articles":
            listing = [{k: a[k] for k in ("id", "published_at")} for a in articles]
            return httpx.Response(200, json=listing)
        match = re.match(r"^/api/articles/(\d+)$", path)
        if match:
            for article in articles:
                if str(article["id"]) == match.group(1):
                    return httpx.Response(200, json=article)
        return httpx.Response(404, json={"error": "not found"})

    def _mastodon(self, request: httpx.Request) -> httpx.Response:
        if not request.url.path.startswith("/api/v1/timelines/tag/"):
            return httpx.Response(404, json={"error": "not found"})
        statuses = self.social.get("mastodon", {}).get("statuses", [])
        return httpx.Response(200, json=statuses, headers={"x-ratelimit-remaining": "299"})

    def _bluesky(self, request: httpx.Request) -> httpx.Response:
        if request.url.path != "/xrpc/app.bsky.feed.searchPosts":
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json=self.social.get("bluesky", {"posts": []}))

    def _lemmy(self, request: httpx.Request) -> httpx.Response:
        if request.url.path != "/api/v3/search":
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json=self.social.get("lemmy", {"posts": []}))

    def _npm(self, request: httpx.Request) -> httpx.Response:
        package = unquote(request.url.path.removeprefix("/downloads/point/last-month/"))
        for repo in self.repos:
            if repo.get("npm_package") == package:
                return httpx.Response(
                    200, json={"downloads": repo.get("npm_downloads", 0), "package": package}
                )
        return httpx.Response(404, json={"error": "package not found"})
