"""Queue candidates, real-time star velocity, the "Nuevas" list and visitor suggestions."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from collector.frontier import Frontier
from collector.github.client import GitHubBudgets
from collector.github.stars import PER_BUILD, refresh_velocity, stars_in_windows
from collector.http import RequestFailedError
from collector.run import _queue_suggestions
from collector.state import StateStore
from indexer.index import _fresh_velocity, candidates_from, star_spike
from indexer.lists import Ranked, newest
from pipeline.config import Budgets
from pipeline.models import RepoMeta
from tests.support import NOW, FakeClock


def test_candidates_are_sanitized_and_skip_published_repos() -> None:
    queue = {
        "a/one": {"id": "a/one", "priority": 2.0, "description": "Uses ‮evil\x00 text", "stars": 5},
        "b/two": {
            "id": "b/two",
            "priority": 9.0,
            "description": "token ghp_" + "A" * 36,
            "topics": ["mcp", "Bad Topic!", "claude-code"],
        },
        "../x": {"id": "../x", "priority": 99.0},
        "c/done": {"id": "c/done", "priority": 50.0},
    }
    out = candidates_from(queue, skip={"c/done"})
    assert [c["id"] for c in out] == ["b/two", "a/one"]  # by priority; invalid and published out
    assert "ghp_" not in out[0]["d"] and "[secreto oculto]" in out[0]["d"]
    assert out[0]["t"] == ["mcp", "claude-code"]
    assert "‮" not in out[1]["d"] and "\x00" not in out[1]["d"]


def test_stars_in_windows_reads_weekly_rows_of_daily_counts() -> None:
    sunday = datetime(2026, 10, 11, tzinfo=UTC)
    history = [
        {"week": int(sunday.timestamp()), "days": [5, 7, 0, 0, 0, 0, 0]},  # Sun 11, Mon 12
        {"week": int((sunday - timedelta(days=7)).timestamp()), "days": [1, 1, 1, 1, 1, 1, 1]},
        {"week": int((sunday - timedelta(days=14)).timestamp()), "days": [2, 2, 2, 2, 2, 2, 2]},
    ]
    last, previous = stars_in_windows(history, datetime(2026, 10, 12, tzinfo=UTC).date())
    assert last == 7 + 5 + 5  # Oct 12, Oct 11 and Oct 6-10 (ages 0-6)
    assert previous == 2 + 10  # Oct 4-5 and Sep 29-Oct 3 (ages 7-13); older days are ignored


class StarApi:
    def __init__(self, fail: dict[str, int] | None = None) -> None:
        self.budgets = GitHubBudgets.from_settings(Budgets(rest=200))
        self.calls: list[str] = []
        self.fail = fail or {}

    def star_history(self, repo_id: str, weeks: int = 3) -> list[dict[str, Any]]:
        self.calls.append(repo_id)
        self.budgets.core.spend(1)
        if repo_id in self.fail:
            raise RequestFailedError("github", self.fail[repo_id], "history")
        week = int(datetime(2026, 10, 11, tzinfo=UTC).timestamp())
        return [{"week": week, "days": [3, 4, 0, 0, 0, 0, 0]}]


def test_velocity_is_measured_once_a_day_and_skips_tiny_repos(tmp_path: Path) -> None:
    state = StateStore(tmp_path / "state.json", FakeClock(NOW))
    store = state.data.setdefault("velocity", {})
    store["fresh/one"] = {"at": "2026-10-12T06:00:00Z", "d7": 1, "p7": 0}
    api = StarApi(fail={"gone/repo": 404})

    class Catalog:
        def __iter__(self):  # type: ignore[no-untyped-def]
            for repo_id, stars in (
                ("big/repo", 900),
                ("fresh/one", 50),
                ("gone/repo", 30),
                ("tiny/repo", 2),
            ):
                owner, name = repo_id.split("/")
                yield type(
                    "R",
                    (),
                    {"meta": RepoMeta(id=repo_id, owner=owner, name=name, url="", stars=stars)},
                )

    measured = refresh_velocity(api, state, Catalog(), NOW)  # type: ignore[arg-type]
    assert api.calls == ["big/repo", "gone/repo"]  # fresh one skipped, tiny one ignored
    assert measured == 1
    assert store["big/repo"]["d7"] == 7
    assert store["gone/repo"]["d7"] is None  # remembered so it is not retried today
    assert _fresh_velocity(store["big/repo"], NOW) == 7
    assert _fresh_velocity(store["big/repo"], NOW + timedelta(days=3)) is None
    assert PER_BUILD >= 3


def _ranked(repo_id: str, total: int, created_days: float | None) -> Ranked:
    return Ranked(repo_id, "skill", "development", total, 0, 0, 0, 0, 0, 10, 0, 0, created_days)


def test_newest_lists_this_month_by_score() -> None:
    items = [
        _ranked("old/a", 90, 400),
        _ranked("new/b", 50, 3),
        _ranked("new/c", 70, 20),
        _ranked("x/d", 99, None),
    ]
    assert newest(items) == ["new/c", "new/b"]


def test_suggestions_are_queued_first_and_capped(tmp_path: Path) -> None:
    state = StateStore(tmp_path / "state.json", FakeClock(NOW))
    frontier = Frontier(state, NOW)
    frontier.add("big/repo", via="search", stars=90_000)
    state.repo("done/repo")["status"] = "artifact"

    class Issues:
        def issues(self, repo_id: str, *, label: str, state: str = "all") -> list[dict[str, Any]]:
            assert label == "suggestion" and state == "open"
            return [
                {"body": "### Repositorio\n\nwanted/skill"},
                {"body": "### Repositorio\n\ndone/repo"},
                {"body": "no repository here"},
                {"body": "x/y", "pull_request": {}},
            ]

    assert _queue_suggestions(Issues(), "me/skillscope", frontier, set()) == 1  # type: ignore[arg-type]
    assert frontier.pop_batch(1)[0]["id"] == "wanted/skill"


def test_star_spike_is_a_plain_fact_about_this_week() -> None:
    assert star_spike(190_365, 200_971)  # 95 % of all stars in seven days
    assert not star_spike(4_965, 91_432)  # steady growth
    assert not star_spike(600, 900)  # too small to mean anything
    assert not star_spike(None, 10)
