"""One full build: collect → social signals → analyze → index → files.

A source that fails is reported in ``index.json → sources`` and the build continues; only a
configuration error stops it (docs/fuentes.md).
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from collector.npm import collect_npm
from collector.run import collect_github
from collector.social.base import run_source
from collector.social.sources import ALL_SOURCES
from indexer import index
from pipeline.clock import iso
from pipeline.context import Context
from pipeline.optout import has_optout_topic
from pipeline.signals import SignalStore
from pipeline.stages import analyze_pending

log = logging.getLogger("skillscope.build")


@dataclass(slots=True)
class BuildResult:
    build_id: str
    built_at: str
    published: int
    catalog: int
    duration_s: float
    sources: list[dict[str, Any]]
    files: dict[str, str]


def run_build(ctx: Context, out_dir: Path, root: Path) -> BuildResult:
    started = ctx.clock.monotonic()
    settings = ctx.settings
    signals = SignalStore(settings.state_dir)
    reports: list[dict[str, Any]] = []

    github = collect_github(
        settings, ctx.clock, ctx.http, ctx.state, ctx.snapshots, root, ctx.catalog
    )
    reports.append(github.report.to_dict())

    for source_class in ALL_SOURCES:
        result = run_source(
            source_class(), http=ctx.http, state=ctx.state, settings=settings, clock=ctx.clock
        )
        signals.add_mentions(result.mentions)
        signals.add_demand(result.demand)
        reports.append(result.report.to_dict())

    analyzed = analyze_pending(ctx.snapshots, ctx.catalog, ctx.state, ctx.clock.now())
    reports[0].setdefault("details", {})["analysis"] = asdict(analyzed)

    records = list(ctx.catalog)
    excluded = set(github.excluded) | {
        r.meta.id.lower() for r in records if has_optout_topic(r.meta.topics)
    }
    now = ctx.clock.now()
    today = now.strftime("%Y-%m-%d")
    for record in records:
        meta = record.meta
        signals.record_repo(
            meta.id, today, stars=meta.stars, forks=meta.forks, commits=meta.commits_30d
        )
    packages = [r.analysis.npm_package for r in records if r.analysis.npm_package]
    npm = collect_npm(
        ctx.http, signals, [p for p in packages if p], budget_limit=settings.budgets.npm, now=now
    )
    reports.append(npm.to_dict())
    signals.prune(now, keep_repos={r.meta.id.lower() for r in records})

    site = index.build(
        records,
        signals,
        site_url=settings.site_url,
        now=now,
        sources=reports,
        excluded=excluded,
        index_max=settings.index_max,
        sample_mode=settings.offline,
    )
    files = index.write(site, out_dir, now)

    signals.save()
    ctx.state.data["last_build"] = {"build_id": site.build_id, "built_at": site.built_at}
    ctx.state.save()
    ctx.raw.prune(keep=ctx.state.referenced_objects(), max_age_days=0)
    duration = round(ctx.clock.monotonic() - started, 1)
    log.info("build %s: %d repos published in %.1fs", site.build_id, len(site.entries), duration)
    _step_summary(site.build_id, len(site.entries), site.catalog_size, duration, reports)
    return BuildResult(
        build_id=site.build_id,
        built_at=iso(now),
        published=len(site.entries),
        catalog=site.catalog_size,
        duration_s=duration,
        sources=reports,
        files=files,
    )


def _step_summary(
    build_id: str, published: int, catalog: int, duration: float, reports: list[dict[str, Any]]
) -> None:
    """Markdown summary for the GitHub Actions run page (no-op elsewhere)."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [
        f"### Build `{build_id}`",
        "",
        f"{published} repos publicados de {catalog} analizados en {duration} s.",
        "",
        "| Fuente | Estado | Llamadas | Motivo |",
        "|---|---|---|---|",
    ]
    for report in reports:
        reason = str(report.get("reason") or "").replace("|", "/")
        status = report.get("status", "ok")
        lines.append(f"| {report['id']} | {status} | {report.get('calls', 0)} | {reason} |")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
