"""Discovery of candidate repositories through GitHub search.

The search API stops at 1,000 results per query (docs/investigacion.md #14), so large topics
are split into date ranges (and code queries into size ranges) until every slice is under
the cap. Slices and their page cursor live in ``state.json`` and are resumed by the next
build, which is how the whole ecosystem gets covered over time within the budget.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from collector.frontier import Frontier
from collector.github.client import GitHubClient, SearchPage
from collector.http import RequestFailedError
from collector.state import StateStore
from pipeline.clock import iso, parse_iso

log = logging.getLogger("skillscope.discovery")

TOPIC_QUERIES: tuple[str, ...] = (
    "topic:claude-skills",
    "topic:claude-code-plugin",
    "topic:claude-skill",
    "topic:agent-skills",
    "topic:claude-code-skills",
    "topic:claude-plugin",
    "topic:claude-code-plugins",
    "topic:claude-plugins",
    "topic:claude-marketplace",
    "topic:claude-code-marketplace",
    "topic:skill-md",
    "topic:claude-code-hooks",
    "topic:claude-code-agents",
    "topic:claude-code-commands",
    "topic:claude-agents",
    "topic:claude-code",
    "claude topic:mcp",
    "claude topic:mcp-server",
)

CODE_QUERIES: tuple[str, ...] = (
    "name filename:SKILL.md",
    "plugins filename:marketplace.json path:.claude-plugin",
    "name filename:plugin.json path:.claude-plugin",
)

SEARCH_CAP = 1000
PER_PAGE = 100
EPOCH = date(2015, 1, 1)
MAX_FILE_SIZE = 400_000
RECRAWL_DAYS = 7
FRONTIER_FULL = 300  # candidates waiting; above this, discovery only looks for fresh repos


@dataclass(slots=True)
class DiscoveryReport:
    queries: int = 0
    found: int = 0
    added: int = 0
    crawl_deferred: bool = False
    errors: list[str] = field(default_factory=list)


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _split_dates(slice_: dict[str, Any]) -> list[dict[str, Any]] | None:
    start, end = _date(slice_["from"]), _date(slice_["to"])
    if start >= end:
        return None
    mid = start + timedelta(days=(end - start).days // 2)
    return [
        {"from": start.isoformat(), "to": mid.isoformat(), "page": 1, "count": None, "done": False},
        {
            "from": (mid + timedelta(days=1)).isoformat(),
            "to": end.isoformat(),
            "page": 1,
            "count": None,
            "done": False,
        },
    ]


def _split_sizes(slice_: dict[str, Any]) -> list[dict[str, Any]] | None:
    low, high = int(slice_["from"]), int(slice_["to"])
    if high - low < 2:
        return None
    mid = (low + high) // 2
    return [
        {"from": low, "to": mid, "page": 1, "count": None, "done": False},
        {"from": mid + 1, "to": high, "page": 1, "count": None, "done": False},
    ]


class Discovery:
    def __init__(
        self,
        gh: GitHubClient,
        state: StateStore,
        frontier: Frontier,
        now: datetime,
        excluded: set[str],
    ) -> None:
        self.gh = gh
        self.state = state
        self.frontier = frontier
        self.now = now
        self.excluded = excluded
        self.report = DiscoveryReport()

    # -- ingestion --------------------------------------------------------------------------
    def _ingest_repos(self, page: SearchPage, via: str) -> None:
        for item in page.items:
            full_name = item.get("full_name")
            if not full_name or item.get("fork"):
                continue
            self.report.found += 1
            if self.frontier.add(
                str(full_name),
                via=via,
                stars=int(item.get("stargazers_count") or 0),
                pushed_at=item.get("pushed_at"),
                excluded=self.excluded,
            ):
                self.report.added += 1

    def _ingest_code(self, page: SearchPage, via: str) -> None:
        for item in page.items:
            repo = item.get("repository") or {}
            full_name = repo.get("full_name")
            if not full_name or repo.get("fork"):
                continue
            self.report.found += 1
            if self.frontier.add(str(full_name), via=via, excluded=self.excluded):
                self.report.added += 1

    # -- passes -----------------------------------------------------------------------------
    def freshness(self, max_queries: int) -> None:
        """Recently pushed repos for a rotating subset of topics (catches updates and new repos)."""
        sinces: dict[str, str] = self.state.cursor("fresh").setdefault("since", {})
        # Least recently checked topics first; never-checked ones sort before everything.
        order = sorted(TOPIC_QUERIES, key=lambda q: (sinces.get(q, ""), q))
        for done, query in enumerate(order):
            if done >= max_queries or not self.gh.budgets.search.can_spend():
                break
            since = parse_iso(sinces.get(query)) or (self.now - timedelta(days=1))
            q = f"{query} pushed:>={iso(since - timedelta(minutes=30))}"
            try:
                page = self.gh.search_repositories(q, page=1, sort="updated")
            except RequestFailedError as exc:
                self.report.errors.append(str(exc))
                break
            self.report.queries += 1
            self._ingest_repos(page, "fresh")
            sinces[query] = iso(self.now)

    def crawl_topics(self) -> None:
        cursor = self.state.cursor("topics")
        order = int(cursor.get("index", 0))
        for offset in range(len(TOPIC_QUERIES)):
            if not self.gh.budgets.search.can_spend():
                return
            query = TOPIC_QUERIES[(order + offset) % len(TOPIC_QUERIES)]
            if self._crawl_query(cursor, query, kind="date"):
                cursor["index"] = (order + offset) % len(TOPIC_QUERIES)
                return
        cursor["index"] = (order + 1) % len(TOPIC_QUERIES)

    def crawl_code(self) -> None:
        cursor = self.state.cursor("code")
        order = int(cursor.get("index", 0))
        for offset in range(len(CODE_QUERIES)):
            if not self.gh.budgets.code_search.can_spend():
                return
            query = CODE_QUERIES[(order + offset) % len(CODE_QUERIES)]
            if self._crawl_query(cursor, query, kind="size"):
                cursor["index"] = (order + offset) % len(CODE_QUERIES)
                return
        cursor["index"] = (order + 1) % len(CODE_QUERIES)

    def _initial_slices(self, kind: str) -> list[dict[str, Any]]:
        if kind == "date":
            return [
                {
                    "from": EPOCH.isoformat(),
                    "to": self.now.date().isoformat(),
                    "page": 1,
                    "count": None,
                    "done": False,
                }
            ]
        return [{"from": 0, "to": MAX_FILE_SIZE, "page": 1, "count": None, "done": False}]

    def _crawl_query(self, cursor: dict[str, Any], query: str, *, kind: str) -> bool:
        """Advance one query through its slices. Returns True when it stopped for budget."""
        slots: dict[str, Any] = cursor.setdefault("queries", {})
        info = slots.setdefault(query, {"slices": None, "cycle_done_at": None})
        if info["slices"] is None or (
            all(s["done"] for s in info["slices"]) and self._cycle_expired(info)
        ):
            info["slices"] = self._initial_slices(kind)
            info["cycle_done_at"] = None
        budget = self.gh.budgets.search if kind == "date" else self.gh.budgets.code_search
        while True:
            pending = [s for s in info["slices"] if not s["done"]]
            if not pending:
                info["cycle_done_at"] = info["cycle_done_at"] or iso(self.now)
                return False
            if not budget.can_spend():
                return True
            current = pending[0]
            if kind == "date":
                q = f"{query} created:{current['from']}..{current['to']}"
            else:
                q = f"{query} size:{current['from']}..{current['to']}"
            try:
                if kind == "date":
                    page = self.gh.search_repositories(q, page=int(current["page"]))
                else:
                    page = self.gh.search_code(q, page=int(current["page"]))
            except RequestFailedError as exc:
                self.report.errors.append(str(exc))
                return True
            self.report.queries += 1
            current["count"] = page.total_count
            if kind == "date":
                self._ingest_repos(page, "topic")
            else:
                self._ingest_code(page, "code")
            if page.total_count > SEARCH_CAP:
                halves = _split_dates(current) if kind == "date" else _split_sizes(current)
                if halves:
                    index = info["slices"].index(current)
                    info["slices"][index : index + 1] = halves
                    continue
            reachable = min(page.total_count, SEARCH_CAP)
            if not page.items or int(current["page"]) * PER_PAGE >= reachable:
                current["done"] = True
            else:
                current["page"] = int(current["page"]) + 1

    def _cycle_expired(self, info: dict[str, Any]) -> bool:
        done_at = parse_iso(info.get("cycle_done_at"))
        return done_at is None or self.now - done_at >= timedelta(days=RECRAWL_DAYS)

    def run(self) -> DiscoveryReport:
        """Look for new repositories. With a long queue only recent ones are searched, so the
        build spends its time analyzing what it already found (search is the slowest API)."""
        if len(self.frontier) >= FRONTIER_FULL:
            self.report.crawl_deferred = True
            self.freshness(max(1, int(self.gh.budgets.search.remaining * 0.25)))
            return self.report
        fresh_quota = max(1, int(self.gh.budgets.search.remaining * 0.4))
        self.freshness(fresh_quota)
        self.crawl_topics()
        self.crawl_code()
        return self.report
