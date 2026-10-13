"""Online collection: GitHub first (the engine), then the social signal sources."""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

from collector.frontier import Frontier
from collector.github.client import GitHubBudgets, GitHubClient
from collector.github.discovery import FRONTIER_FULL, Discovery
from collector.github.enrich import Enricher
from collector.github.stars import refresh_velocity
from collector.http import DEADLINE_MESSAGE, HttpClient, RequestFailedError
from collector.snapshots import SnapshotStore
from collector.state import StateStore
from pipeline import optout
from pipeline.catalog import CatalogStore
from pipeline.clock import Clock
from pipeline.config import Settings
from pipeline.report import SourceReport

log = logging.getLogger("skillscope.collect")

OFFICIAL_SEEDS = (
    "anthropics/claude-plugins-official",
    "anthropics/claude-plugins-community",
    "anthropics/claude-code",
    "anthropics/skills",
)
CATCH_UP_MIN_LIMIT = 5000  # calls per hour of a personal token; GITHUB_TOKEN has 1,000
SUGGESTION_LABEL = "suggestion"
MAX_SUGGESTIONS = 20


@dataclass(slots=True)
class GitHubRun:
    report: SourceReport
    excluded: set[str]


def load_seed(path: Path) -> list[str]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return [row["repo"] for row in csv.DictReader(fh) if row.get("repo")]


def _queue_suggestions(
    gh: GitHubClient, repository: str, frontier: Frontier, excluded: set[str]
) -> int | str:
    """Repositories visitors asked to analyze (issue form "Sugerir un repositorio").

    Issue text is untrusted: only an ``owner/repo`` matching GitHub's naming rules is taken,
    at most ``MAX_SUGGESTIONS`` per build, and a repository already analyzed is not queued.
    """
    try:
        issues = gh.issues(repository, label=SUGGESTION_LABEL, state="open")
    except RequestFailedError as exc:
        return exc.reason
    queued = 0
    for issue in issues[:MAX_SUGGESTIONS]:
        if "pull_request" in issue:
            continue
        repo_id = optout.repo_from_issue(str(issue.get("body") or ""))
        if repo_id and frontier.add(repo_id, via="suggestion", excluded=excluded):
            queued += 1
    return queued


def catching_up(budgets: GitHubBudgets, queued: int) -> bool:
    """Run the next build right away while the queue is long and the hourly quota allows it.

    Only with a personal token (5,000 calls/h): the repository GITHUB_TOKEN has 1,000/h,
    which back-to-back builds would exhaust (docs/fuentes.md).
    """
    if queued < FRONTIER_FULL:
        return False
    if any(b.closed for b in budgets.all().values()):
        return False
    return all(
        (b.observed_limit or 0) >= CATCH_UP_MIN_LIMIT for b in (budgets.core, budgets.graphql)
    )


def collect_github(
    settings: Settings,
    clock: Clock,
    http: HttpClient,
    state: StateStore,
    snapshots: SnapshotStore,
    root: Path,
    catalog: CatalogStore | None = None,
) -> GitHubRun:
    started = clock.monotonic()
    report = SourceReport(id="github")
    if not settings.github_token:  # load_settings already refuses this in online mode
        report.status, report.reason = "skipped", "no token"
        return GitHubRun(report, set())
    budgets = GitHubBudgets.from_settings(settings.budgets)
    gh = GitHubClient(http, settings.github_token, budgets)
    now = clock.now()

    try:
        gh.preflight()
    except RequestFailedError as exc:
        report.status, report.reason = "failed", f"rate_limit preflight: {exc.reason}"
        return GitHubRun(report, set())

    excluded = optout.from_file(settings.config_dir / "optout.txt")
    if settings.repository:
        try:
            excluded |= optout.from_issues(
                gh.issues(settings.repository, label=optout.OPTOUT_LABEL)
            )
        except RequestFailedError as exc:
            report.details["optout_issues"] = exc.reason
    for repo_id in excluded:
        state.repo(repo_id)["status"] = "opted_out"
        snapshots.delete(repo_id)
        if catalog is not None:
            catalog.delete(repo_id)

    frontier = Frontier(state, now)
    if not settings.offline and not state.data.get("seeded"):
        for repo_id in (*OFFICIAL_SEEDS, *load_seed(root / "data" / "seed" / "repos.csv")):
            frontier.add(repo_id, via="seed", excluded=excluded)
        state.data["seeded"] = True
    if settings.repository:
        report.details["suggested"] = _queue_suggestions(
            gh, settings.repository, frontier, excluded
        )

    discovery = Discovery(gh, state, frontier, now, excluded).run()
    # Trends first: a few cheap calls that analysis (which uses all the time left) cannot starve.
    velocity = refresh_velocity(gh, state, catalog, now) if catalog is not None else 0
    enrich = Enricher(gh, state, snapshots, frontier, now, excluded, catalog).run()

    report.calls = sum(b.calls for b in budgets.all().values())
    report.budget = sum(b.limit for b in budgets.all().values())
    report.duration_ms = int((clock.monotonic() - started) * 1000)
    report.details |= {
        "budgets": {name: b.report() for name, b in budgets.all().items()},
        "discovery": {
            "queries": discovery.queries,
            "found": discovery.found,
            "added": discovery.added,
            "crawl_deferred": discovery.crawl_deferred,
        },
        "enrich": {
            "refreshed": enrich.refreshed,
            "analyzed": enrich.analyzed,
            "unchanged": enrich.unchanged,
            "no_artifacts": enrich.no_artifacts,
            "internal": enrich.internal,
            "gone": enrich.gone,
        },
        "frontier": len(frontier),
        "velocity": velocity,
        "catch_up": catching_up(budgets, len(frontier)),
    }
    # Running out of build time is the normal end of a build, not a failure: the queue waits.
    errors = [e for e in discovery.errors + enrich.errors if DEADLINE_MESSAGE not in e]
    report.details["deadline_reached"] = len(errors) < len(discovery.errors + enrich.errors)
    if errors:
        report.status = "partial"
        report.reason = errors[0][:200]
        report.details["errors"] = len(errors)
        report.details["first_errors"] = [error[:200] for error in errors[:3]]
    return GitHubRun(report, excluded)
