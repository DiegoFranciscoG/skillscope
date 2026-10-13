"""End-to-end GitHub collection against the sample API (no network)."""

from pathlib import Path

from collector.run import collect_github
from collector.snapshots import SnapshotStore
from pipeline.clock import FakeClock
from pipeline.config import load_settings
from pipeline.sample_api import SampleApi
from tests.support import NOW, SAMPLES, make_harness

ENV = {
    "SKILLSCOPE_GITHUB_TOKEN": "test-token",
    "SKILLSCOPE_SITE_URL": "https://example.test/skillscope/",
    "SKILLSCOPE_BUDGET_SEARCH": "100",
    "SKILLSCOPE_BUDGET_CODE_SEARCH": "20",
}


def _run(tmp: Path, api: SampleApi, clock: FakeClock, env: dict[str, str] | None = None):
    settings = load_settings(env or ENV, offline=False, root=tmp)
    h = make_harness(tmp / "work", api=api, clock=clock)
    snapshots = SnapshotStore(tmp / "snapshots")
    result = collect_github(settings, clock, h.http, h.state, snapshots, root=tmp)
    h.state.save()
    return result, snapshots, h


def test_first_build_snapshots_every_sample_with_artifacts(tmp_path: Path) -> None:
    clock = FakeClock(NOW)
    api = SampleApi(SAMPLES, clock)
    env = ENV | {"SKILLSCOPE_BUDGET_REST": "200", "SKILLSCOPE_BUDGET_GRAPHQL": "200"}
    result, snapshots, _ = _run(tmp_path, api, clock, env)

    ids = {s.id for s in snapshots}
    assert "demo_nimbus-labs/pr-review-kit" in ids
    assert "demo_awesome-agentic/awesome-skill-index" in ids  # README-only list is kept
    assert len(ids) == len(api.repos)
    snap = snapshots.load("demo_nimbus-labs/pr-review-kit")
    assert snap is not None
    assert "skills/review-diff/SKILL.md" in snap.files
    assert snap.meta.stars == 8200 and snap.meta.ci_state == "SUCCESS"
    assert result.report.status in {"ok", "partial"}
    assert sum(api.overruns.values()) == 0


def test_second_build_reuses_etags_and_skips_unchanged_trees(tmp_path: Path) -> None:
    clock = FakeClock(NOW)
    api = SampleApi(SAMPLES, clock)
    env = ENV | {"SKILLSCOPE_BUDGET_REST": "200", "SKILLSCOPE_BUDGET_GRAPHQL": "200"}
    _run(tmp_path, api, clock, env)
    trees_first = api.calls["core"]
    clock.advance(15 * 60)
    result, _, _ = _run(tmp_path, api, clock, env)
    assert api.calls["core"] == trees_first  # nothing changed, no tree downloaded again
    assert result.report.details["enrich"]["refreshed"] > 0


def test_build_never_exceeds_api_limits(tmp_path: Path) -> None:
    """Acceptance: with tight quotas the collector stops before the API says no."""
    clock = FakeClock(NOW)
    api = SampleApi(
        SAMPLES, clock, limits={"core": 25, "search": 8, "code_search": 4, "graphql": 12}
    )
    env = ENV | {
        "SKILLSCOPE_BUDGET_REST": "500",
        "SKILLSCOPE_BUDGET_GRAPHQL": "500",
        "SKILLSCOPE_BUDGET_SEARCH": "100",
        "SKILLSCOPE_BUDGET_CODE_SEARCH": "50",
    }
    result, snapshots, _ = _run(tmp_path, api, clock, env)
    assert sum(api.overruns.values()) == 0, api.overruns
    # 10 % of every quota is kept as reserve
    assert api.calls["core"] <= 25 - 3
    assert api.calls["search"] <= 8 - 1
    assert api.calls["code_search"] <= 4 - 1
    assert api.calls["graphql"] <= 12 - 2
    budgets = result.report.details["budgets"]
    assert budgets["core"]["used"] <= budgets["core"]["budget"]
    assert len(list(snapshots)) > 0  # partial progress is kept for the next build


def test_optout_issue_from_owner_removes_repo(tmp_path: Path) -> None:
    clock = FakeClock(NOW)
    issues = [
        {"body": "demo_acme-agents/inbox-zero", "user": {"login": "demo_acme-agents"}, "labels": []}
    ]
    api = SampleApi(SAMPLES, clock, issues=issues)
    env = ENV | {"SKILLSCOPE_REPOSITORY": "me/skillscope", "SKILLSCOPE_BUDGET_REST": "200"}
    result, snapshots, h = _run(tmp_path, api, clock, env)
    assert "demo_acme-agents/inbox-zero" in result.excluded
    assert snapshots.load("demo_acme-agents/inbox-zero") is None
    assert h.state.known_repo("demo_acme-agents/inbox-zero")["status"] == "opted_out"
