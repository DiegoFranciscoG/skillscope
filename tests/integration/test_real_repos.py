"""Analyzer against real public repositories from the seed list.

Skipped by default. Run with a token:  GITHUB_TOKEN=... uv run pytest -m network
Only metadata and the files the analyzer needs are fetched through the official API.
"""

import os
from pathlib import Path

import httpx
import pytest

from analyzer.analyze import analyze_all
from analyzer.detect import layout, select_files
from collector.github.client import GitHubBudgets, GitHubClient
from collector.http import HttpClient
from collector.rawstore import RawStore
from collector.state import StateStore
from pipeline.clock import SystemClock
from pipeline.config import Budgets
from pipeline.models import RepoSnapshot

REPOS = [
    "anthropics/skills",
    "anthropics/claude-plugins-official",
    "wshobson/agents",
    "blader/humanizer",
]

pytestmark = pytest.mark.network


@pytest.mark.skipif(not os.environ.get("GITHUB_TOKEN"), reason="needs GITHUB_TOKEN")
def test_real_repositories_are_classified(tmp_path: Path) -> None:
    clock = SystemClock()
    state = StateStore(tmp_path / "state.json", clock)
    http = HttpClient(
        client=httpx.Client(timeout=30, follow_redirects=True),
        state=state,
        raw=RawStore(tmp_path / "raw", clock),
        clock=clock,
        deadline=clock.monotonic() + 300,
    )
    gh = GitHubClient(
        http, os.environ["GITHUB_TOKEN"], GitHubBudgets.from_settings(Budgets(rest=20, graphql=40))
    )
    metas = gh.repo_meta(REPOS, clock.now())
    snapshots = []
    for meta in metas.values():
        tree = gh.tree(meta.id, str(meta.head_oid))
        wanted = select_files(layout(tree.entries), {e.path: e.size for e in tree.entries})
        texts = {}
        for start in range(0, len(wanted), 40):
            texts.update(
                gh.blobs([(meta.id, str(meta.head_oid), p) for p in wanted[start : start + 40]])
            )
        files = {p: texts[(meta.id.lower(), p)] for p in wanted if (meta.id.lower(), p) in texts}
        snapshots.append(RepoSnapshot(meta=meta, tree=tree.entries, files=files))
    result = analyze_all(snapshots, clock.now())
    types = {a.id: a.type for a in result.analyses}
    assert types["anthropics/skills"] == "marketplace"
    assert types["anthropics/claude-plugins-official"] == "marketplace"
    skills = next(a for a in result.analyses if a.id == "anthropics/skills")
    assert sum(1 for a in skills.artifacts if a.kind == "skill" and a.valid) >= 5
    for item in result.analyses:
        assert item.summary_lead and item.install.kind
