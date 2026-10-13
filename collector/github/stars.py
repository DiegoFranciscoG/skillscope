"""Stars gained in the last 7 days, from GitHub's aggregated star history (investigación #59).

``GET /repos/{owner}/{repo}/stargazers/history`` returns stars per day grouped by week and no
per-user data. It makes "En tendencia" real from the first build instead of waiting a week of
our own snapshots. The per-user stargazer list is no longer usable: since July 2026 it is
restricted to admins and collaborators.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from collector.github.client import GitHubClient
from collector.http import DeadlineReachedError, RequestFailedError
from collector.state import StateStore
from pipeline.catalog import CatalogStore
from pipeline.clock import iso, parse_iso

PER_BUILD = 40
MAX_AGE = timedelta(hours=20)
MIN_STARS = 10  # below this a weekly count says nothing
CORE_RESERVE = 20  # REST calls kept for trees of new repositories
WINDOW_DAYS = 7


def stars_in_windows(history: list[dict[str, Any]], today: date) -> tuple[int, int]:
    """Stars of the last 7 days and of the 7 days before, from weekly rows of daily counts."""
    last = previous = 0
    for week in history:
        start = datetime.fromtimestamp(int(week.get("week") or 0), tz=UTC).date()
        for offset, count in enumerate(week.get("days") or []):
            age = (today - (start + timedelta(days=offset))).days
            if 0 <= age < WINDOW_DAYS:
                last += int(count or 0)
            elif WINDOW_DAYS <= age < 2 * WINDOW_DAYS:
                previous += int(count or 0)
    return last, previous


def refresh_velocity(
    gh: GitHubClient, state: StateStore, catalog: CatalogStore, now: datetime
) -> int:
    """Measure the stalest indexed repositories first; returns how many were measured."""
    store: dict[str, Any] = state.data.setdefault("velocity", {})
    due: list[tuple[str, int, str]] = []
    for record in catalog:
        meta = record.meta
        if meta.stars < MIN_STARS:
            continue
        measured = parse_iso((store.get(meta.id.lower()) or {}).get("at"))
        if measured is None or now - measured >= MAX_AGE:
            due.append((iso(measured) if measured else "", -meta.stars, meta.id))
    measured_count = 0
    for _, _, repo_id in sorted(due)[:PER_BUILD]:
        core = gh.budgets.core
        if not core.can_spend() or core.remaining <= CORE_RESERVE:
            break
        try:
            history = gh.star_history(repo_id)
        except DeadlineReachedError:
            break
        except RequestFailedError as exc:
            if exc.status not in (404, 422):
                break
            store[repo_id.lower()] = {"at": iso(now), "d7": None, "p7": None}
            continue
        last, previous = stars_in_windows(history, now.astimezone(UTC).date())
        store[repo_id.lower()] = {"at": iso(now), "d7": last, "p7": previous}
        measured_count += 1
    return measured_count
