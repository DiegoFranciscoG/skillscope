from pathlib import Path
from typing import Any

import httpx

from collector.frontier import Frontier
from collector.github.client import GitHubBudgets, GitHubClient
from collector.github.discovery import (
    FRONTIER_FULL,
    TOPIC_QUERIES,
    Discovery,
    _split_dates,
    _split_sizes,
)
from pipeline.config import Budgets
from tests.support import NOW, make_harness


def _fake_search(log: list[str]) -> httpx.MockTransport:
    """Pretends the first wide date slice has 1,500 hits so the crawler must split it."""

    def handler(request: httpx.Request) -> httpx.Response:
        q = request.url.params.get("q", "")
        log.append(q)
        page = int(request.url.params.get("page", 1))
        total = 1500 if "created:2015-01-01..2026-10-12" in q else 150
        items: list[dict[str, Any]] = [
            {"full_name": f"o{page}/r{i}-{len(log)}", "stargazers_count": i, "pushed_at": None}
            for i in range(3)
        ]
        items.append({"full_name": "fork/x", "fork": True})
        return httpx.Response(
            200, json={"total_count": total, "incomplete_results": False, "items": items}
        )

    return httpx.MockTransport(handler)


def test_split_helpers() -> None:
    halves = _split_dates({"from": "2026-01-01", "to": "2026-01-10"})
    assert halves is not None
    assert [h["from"] for h in halves] == ["2026-01-01", "2026-01-06"]
    assert halves[0]["to"] == "2026-01-05"
    assert _split_dates({"from": "2026-01-01", "to": "2026-01-01"}) is None
    sizes = _split_sizes({"from": 0, "to": 100})
    assert sizes is not None and sizes[1]["from"] == 51
    assert _split_sizes({"from": 5, "to": 6}) is None


def test_large_slices_are_split_and_paginated(tmp_path: Path) -> None:
    log: list[str] = []
    h = make_harness(tmp_path, handler=_fake_search(log))
    budgets = GitHubBudgets.from_settings(Budgets(search=4, code_search=0))
    gh = GitHubClient(h.http, "test-token", budgets)
    frontier = Frontier(h.state, NOW)
    discovery = Discovery(gh, h.state, frontier, NOW, excluded=set())
    discovery.crawl_topics()

    assert "created:2015-01-01..2026-10-12" in log[0]
    # second call targets the first half of the split range
    assert "created:2015-01-01..2020-11-21" in log[1]
    assert budgets.search.used == 4
    slices = h.state.cursor("topics")["queries"][TOPIC_QUERIES[0]]["slices"]
    assert len(slices) == 2
    assert slices[0]["page"] == 2  # 150 hits -> two pages; first page consumed
    assert "fork/x" not in frontier.items
    assert len(frontier) > 0


def test_crawl_resumes_from_saved_cursor(tmp_path: Path) -> None:
    log: list[str] = []
    h = make_harness(tmp_path, handler=_fake_search(log))
    for expected_calls in (2, 4):
        budgets = GitHubBudgets.from_settings(Budgets(search=2, code_search=0))
        gh = GitHubClient(h.http, "test-token", budgets)
        Discovery(gh, h.state, Frontier(h.state, NOW), NOW, excluded=set()).crawl_topics()
        assert len(log) == expected_calls
    # third query of the run sequence is page 2 of the first half, not a restart
    assert "created:2015-01-01..2020-11-21" in log[2]


def test_freshness_rotates_least_recent_topics(tmp_path: Path) -> None:
    log: list[str] = []
    h = make_harness(tmp_path, handler=_fake_search(log))
    budgets = GitHubBudgets.from_settings(Budgets(search=30, code_search=0))
    gh = GitHubClient(h.http, "test-token", budgets)
    Discovery(gh, h.state, Frontier(h.state, NOW), NOW, excluded=set()).freshness(3)
    Discovery(gh, h.state, Frontier(h.state, NOW), NOW, excluded=set()).freshness(3)
    topics_first = {q.split(" pushed")[0] for q in log[:3]}
    topics_second = {q.split(" pushed")[0] for q in log[3:]}
    assert not topics_first & topics_second
    assert all("pushed:>=" in q for q in log)


def test_excluded_repos_never_enter_frontier(tmp_path: Path) -> None:
    h = make_harness(tmp_path, handler=_fake_search([]))
    frontier = Frontier(h.state, NOW)
    assert not frontier.add("Owner/Repo", via="x", excluded={"owner/repo"})
    h.state.repo("gone/repo")["status"] = "gone"
    assert not frontier.add("gone/repo", via="x")
    assert frontier.add("ok/repo", via="x", stars=10)
    assert not frontier.add("ok/repo", via="y", stars=5)  # merged, not counted as new
    entry = frontier.items["ok/repo"]
    assert entry["via"] == ["x", "y"] and entry["stars"] == 10


def test_long_queue_defers_the_wide_crawl(tmp_path: Path) -> None:
    log: list[str] = []
    h = make_harness(tmp_path, handler=_fake_search(log))
    budgets = GitHubBudgets.from_settings(Budgets(search=20, code_search=5))
    gh = GitHubClient(h.http, "test-token", budgets)
    frontier = Frontier(h.state, NOW)
    for i in range(FRONTIER_FULL):
        frontier.add(f"queued/r{i}", via="seed")

    report = Discovery(gh, h.state, frontier, NOW, excluded=set()).run()

    assert report.crawl_deferred
    assert budgets.search.used <= 10  # a quarter for fresh repos and a quarter of wide crawl
    assert budgets.code_search.used == 0
