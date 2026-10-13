"""One failing GraphQL batch must never stop the build (live failure of 2026-10-13)."""

from datetime import datetime
from pathlib import Path

from analyzer.detect import Layout
from collector.frontier import Frontier
from collector.github.client import GitHubBudgets
from collector.github.enrich import MAX_META_FAILURES, Enricher, _internal_only
from collector.http import RequestFailedError
from collector.snapshots import SnapshotStore
from collector.state import StateStore
from pipeline.config import Budgets
from pipeline.models import RepoMeta
from tests.support import NOW, FakeClock


class FlakyGitHub:
    """Times out on queries with more than two repositories or with ``bad/repo``."""

    def __init__(self, graphql_budget: int = 50) -> None:
        self.budgets = GitHubBudgets.from_settings(Budgets(graphql=graphql_budget))
        self.queries: list[list[str]] = []

    def repo_meta(self, ids: list[str], now: datetime) -> dict[str, RepoMeta]:
        self.queries.append(list(ids))
        self.budgets.graphql.spend(1)
        if len(ids) > 2 or "bad/repo" in ids:
            raise RequestFailedError("github", 502, "HTTP 502 for https://api.github.com/graphql")
        return {
            i.lower(): RepoMeta(id=i, owner=i.split("/")[0], name=i.split("/")[1], url="")
            for i in ids
        }


def _enricher(tmp_path: Path, gh: FlakyGitHub) -> Enricher:
    state = StateStore(tmp_path / "state.json", FakeClock(NOW))
    return Enricher(
        gh,  # type: ignore[arg-type]
        state,
        SnapshotStore(tmp_path / "snapshots"),
        Frontier(state, NOW),
        NOW,
        excluded=set(),
    )


def test_failed_batch_is_split_until_only_the_bad_repository_is_left(tmp_path: Path) -> None:
    gh = FlakyGitHub()
    enricher = _enricher(tmp_path, gh)
    ids = [f"ok/r{i}" for i in range(7)] + ["bad/repo"]

    metas, failed = enricher._meta(ids)

    assert failed == {"bad/repo"}
    assert set(metas) == {f"ok/r{i}" for i in range(7)}
    assert len(enricher.report.errors) >= 1


def test_closed_budget_leaves_the_rest_for_the_next_build(tmp_path: Path) -> None:
    gh = FlakyGitHub(graphql_budget=1)
    enricher = _enricher(tmp_path, gh)
    metas, failed = enricher._meta([f"ok/r{i}" for i in range(6)])
    assert metas == {} and len(failed) == 6
    assert enricher._may_retry("ok/r0")  # not the repository's fault: keep it queued


def test_repository_that_keeps_failing_is_dropped(tmp_path: Path) -> None:
    enricher = _enricher(tmp_path, FlakyGitHub())
    results = [enricher._may_retry("bad/repo") for _ in range(MAX_META_FAILURES)]
    assert results[:-1] == [True] * (MAX_META_FAILURES - 1) and results[-1] is False
    assert enricher.state.repo("bad/repo")["status"] == "unavailable"


def test_application_with_internal_skills_is_not_a_kit() -> None:
    lay = Layout(skills=[".claude/skills/codebase-design/SKILL.md"])
    app = [".claude/skills/codebase-design/SKILL.md"] + [f"src/f{i}.ts" for i in range(400)]
    kit = [".claude/skills/codebase-design/SKILL.md", "README.md", "LICENSE"]
    assert _internal_only(lay, app)
    assert not _internal_only(lay, kit)
    shipped = Layout(skills=["skills/review/SKILL.md"])
    assert not _internal_only(shipped, ["skills/review/SKILL.md", *app])
    plugin = Layout(
        skills=[".claude/skills/x/SKILL.md"], plugin_manifests=[".claude-plugin/plugin.json"]
    )
    assert not _internal_only(plugin, app)
