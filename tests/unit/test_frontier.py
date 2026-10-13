from pathlib import Path

from collector.frontier import Frontier, priority
from tests.support import NOW, make_harness


def test_priority_formula() -> None:
    # log10(1 + 999) + 0.5·2 + 0.3·2^(0/30) = 3 + 1 + 0.3
    assert priority(999, 2, "2026-10-12T12:00:00Z", NOW) == 4.3
    assert priority(0, 1, None, NOW) == 0.5
    # 30 days old halves the recency bonus
    assert priority(0, 0, "2026-09-12T12:00:00Z", NOW) == 0.15


def test_pop_batch_returns_highest_priority_first(tmp_path: Path) -> None:
    h = make_harness(tmp_path)
    frontier = Frontier(h.state, NOW)
    frontier.add("a/low", via="x", stars=1)
    frontier.add("b/high", via="x", stars=5000)
    frontier.add("c/mid", via="x", stars=100)
    batch = frontier.pop_batch(2)
    assert [e["id"] for e in batch] == ["b/high", "c/mid"]
    assert len(frontier) == 1
    frontier.push_back(batch)
    assert len(frontier) == 3


def test_frontier_persists_in_state(tmp_path: Path) -> None:
    h = make_harness(tmp_path)
    Frontier(h.state, NOW).add("a/b", via="seed")
    h.state.save()
    from collector.state import StateStore

    reloaded = StateStore(tmp_path / "state.json", h.clock)
    assert "a/b" in Frontier(reloaded, NOW).items


def test_analyzed_repos_are_not_queued_again(tmp_path: Path) -> None:
    h = make_harness(tmp_path)
    frontier = Frontier(h.state, NOW)
    h.state.repo("done/skill")["status"] = "artifact"
    assert not frontier.add("done/skill", via="search")
    empty = h.state.repo("empty/repo")
    empty.update(status="no_artifact", analyzed_at="2026-10-10T00:00:00Z")
    assert not frontier.add("empty/repo", via="search", pushed_at="2026-10-09T00:00:00Z")
    assert frontier.add("empty/repo", via="search", pushed_at="2026-10-11T00:00:00Z")


def test_search_metadata_is_kept_and_suggestions_jump_the_queue(tmp_path: Path) -> None:
    h = make_harness(tmp_path)
    frontier = Frontier(h.state, NOW)
    frontier.add(
        "big/repo", via="search", stars=50_000, description="  An  MCP\nserver ", topics=["mcp"]
    )
    frontier.add("small/asked", via="suggestion", stars=0)
    assert frontier.items["big/repo"]["description"] == "An MCP server"
    assert frontier.items["big/repo"]["topics"] == ["mcp"]
    assert [e["id"] for e in frontier.pop_batch(1)] == ["small/asked"]
