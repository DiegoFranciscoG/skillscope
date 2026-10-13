"""Build stages that sit between collection and indexing."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime

from analyzer.analyze import analyze_snapshot
from collector.snapshots import SnapshotStore
from collector.state import StateStore
from pipeline.catalog import CatalogStore

log = logging.getLogger("skillscope.analyze")


@dataclass(slots=True)
class AnalyzeReport:
    analyzed: int = 0
    opted_out: int = 0
    failed: int = 0


SLOW_ANALYSIS_S = 10.0


def analyze_pending(
    snapshots: SnapshotStore, catalog: CatalogStore, state: StateStore, now: datetime
) -> AnalyzeReport:
    """Analyze the snapshots fetched in this build and cache the result by commit."""
    report = AnalyzeReport()
    for snapshot in list(snapshots):
        started = time.perf_counter()
        try:
            analysis = analyze_snapshot(snapshot, now)
        except Exception:  # one malformed repository must never break the build
            log.exception("analysis failed for %s", snapshot.id)
            report.failed += 1
            snapshots.delete(snapshot.id)
            continue
        spent = time.perf_counter() - started
        if spent > SLOW_ANALYSIS_S:
            log.warning("analysis of %s took %.1f s", snapshot.id, spent)
        if analysis is None:
            catalog.delete(snapshot.id)
            state.repo(snapshot.id)["status"] = "opted_out"
            report.opted_out += 1
        else:
            first_seen = state.repo(snapshot.id).get("first_seen")
            catalog.put(analysis, now=now, first_seen=first_seen)
            report.analyzed += 1
        snapshots.delete(snapshot.id)
    return report
