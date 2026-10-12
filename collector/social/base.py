"""Common pieces for social sources: link extraction, mention ids, cadence and isolation.

Rules (docs/fuentes.md): each source has a call budget per build, its own cadence, ETag
caching through ``HttpClient`` and back-off. A failing source is reported and skipped; the
build always continues with the others.
"""

from __future__ import annotations

import hashlib
import html
import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from analyzer.taxonomy import github_links
from collector.budget import Budget
from collector.http import HttpClient, RequestFailedError
from collector.state import StateStore
from pipeline.clock import Clock, iso, parse_iso
from pipeline.config import Settings
from pipeline.models import DemandItem, Mention
from pipeline.report import SourceReport

log = logging.getLogger("skillscope.social")

HREF_RE = re.compile(r'href="([^"]+)"')
TAG_RE = re.compile(r"<[^>]+>")


@dataclass(slots=True)
class SocialResult:
    report: SourceReport
    mentions: list[Mention] = field(default_factory=list)
    demand: list[DemandItem] = field(default_factory=list)


def mention_key(source: str, item_id: str, repo_id: str) -> str:
    """Pseudonymous id used only to avoid counting the same post twice."""
    raw = f"{source}:{item_id}:{repo_id.lower()}".encode()
    return hashlib.sha256(raw).hexdigest()[:20]


def html_text(value: str | None) -> str:
    """Plain text plus link targets from a small HTML fragment (Mastodon, Stack Exchange)."""
    if not value:
        return ""
    links = " ".join(HREF_RE.findall(value))
    return f"{html.unescape(TAG_RE.sub(' ', value))} {links}"


def mentions_from(
    source: str, item_id: str, texts: Iterable[str | None], day: str, engagement: int
) -> list[Mention]:
    joined = " ".join(t for t in texts if t)
    return [
        Mention(source, mention_key(source, item_id, repo), repo, day, max(0, engagement))
        for repo in github_links(joined)
    ]


class SocialSource(ABC):
    id: str = "source"
    cadence_minutes: int = 60
    budget: int = 5

    def unavailable(self, settings: Settings) -> str | None:
        """Reason why the source cannot run (missing credentials), or None."""
        return None

    @abstractmethod
    def fetch(
        self,
        http: HttpClient,
        budget: Budget,
        state: StateStore,
        settings: Settings,
        now: datetime,
    ) -> tuple[list[Mention], list[DemandItem]]: ...


def run_source(
    source: SocialSource,
    *,
    http: HttpClient,
    state: StateStore,
    settings: Settings,
    clock: Clock,
) -> SocialResult:
    report = SourceReport(id=source.id, budget=source.budget)
    reason = source.unavailable(settings)
    if reason:
        report.status, report.reason = "skipped", reason
        return SocialResult(report)
    if not state.is_due(source.id):
        report.status = "skipped"
        report.reason = f"cadencia: próxima consulta {state.data['schedule'][source.id]}"
        return SocialResult(report)
    budget = Budget(source.id, source.budget)
    started = clock.monotonic()
    try:
        mentions, demand = source.fetch(http, budget, state, settings, clock.now())
    except RequestFailedError as exc:
        report.status, report.reason = "failed", exc.reason[:200]
        mentions, demand = [], []
        log.warning("%s failed: %s", source.id, exc.reason)
    except (KeyError, TypeError, ValueError) as exc:  # unexpected payload shape
        report.status, report.reason = "failed", f"respuesta inesperada: {type(exc).__name__}"
        mentions, demand = [], []
    # Keep a longer pause if the source asked for one (e.g. Stack Exchange ``backoff``).
    planned = clock.now() + timedelta(minutes=source.cadence_minutes)
    current = parse_iso(state.data["schedule"].get(source.id))
    if current is None or current < planned:
        state.data["schedule"][source.id] = iso(planned)
    report.calls = budget.calls
    report.duration_ms = int((clock.monotonic() - started) * 1000)
    report.details = {"mentions": len(mentions), "demand": len(demand)}
    return SocialResult(report, mentions, demand)
