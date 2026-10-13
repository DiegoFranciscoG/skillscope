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
from indexer import badges, feeds, index, pages
from pipeline.clock import iso
from pipeline.context import Context
from pipeline.optout import has_optout_topic
from pipeline.signals import SignalStore
from pipeline.stages import analyze_pending

log = logging.getLogger("skillscope.build")

SOURCES_RESERVE_S = 60.0  # seconds kept for social sources and npm after GitHub


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

    # GitHub can always use more time; keep a slice for the social sources and npm after it.
    full_deadline = ctx.http.deadline
    ctx.http.deadline = full_deadline - min(SOURCES_RESERVE_S, 0.2 * settings.max_seconds)
    try:
        github = collect_github(
            settings, ctx.clock, ctx.http, ctx.state, ctx.snapshots, root, ctx.catalog
        )
    finally:
        ctx.http.deadline = full_deadline
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
    for line in github_digest(reports[0]):
        log.info("github: %s", line)

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
        queue=ctx.state.data.get("frontier") or {},
        velocity=ctx.state.data.get("velocity") or {},
    )
    files = index.write(site, out_dir, now)
    feeds.write(site, out_dir, now)
    pages_written = pages.write(site, out_dir, now)
    badges.write(site, out_dir)
    log.info("static pages: %d", pages_written)

    signals.save()
    ctx.state.data["last_build"] = {"build_id": site.build_id, "built_at": site.built_at}
    ctx.state.save()
    ctx.raw.prune(keep=ctx.state.referenced_objects(), max_age_days=0)
    duration = round(ctx.clock.monotonic() - started, 1)
    log.info("build %s: %d repos published in %.1fs", site.build_id, len(site.entries), duration)
    _step_summary(site.build_id, len(site.entries), site.catalog_size, duration, reports)
    details = reports[0].get("details") or {}
    _job_outputs(
        published=len(site.entries),
        queue=int(details.get("frontier", 0)),
        catch_up="true" if details.get("catch_up") else "false",
    )
    return BuildResult(
        build_id=site.build_id,
        built_at=iso(now),
        published=len(site.entries),
        catalog=site.catalog_size,
        duration_s=duration,
        sources=reports,
        files=files,
    )


def _job_outputs(**values: object) -> None:
    """Expose values to later jobs of the workflow (GITHUB_OUTPUT); no-op outside Actions."""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.writelines(f"{key}={value}\n" for key, value in values.items())


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
    github = next((r for r in reports if r.get("id") == "github"), None)
    if github:
        lines += ["", "**GitHub**", ""] + [f"- {line}" for line in github_digest(github)]
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def github_digest(report: dict[str, Any]) -> list[str]:
    """Human summary of the GitHub collection: budgets, discovery, analysis and first errors."""
    details = report.get("details") or {}
    lines: list[str] = []
    budgets = details.get("budgets") or {}
    if budgets:
        parts = []
        for name, budget in budgets.items():
            part = f"{name} {budget.get('used', 0)}/{budget.get('budget', 0)}"
            if budget.get("closed"):
                part += f" (cerrado: {budget['closed']})"
            parts.append(part)
        lines.append("presupuesto " + ", ".join(parts))
    found = details.get("discovery") or {}
    if found:
        deferred = " · búsqueda amplia diferida (cola llena)" if found.get("crawl_deferred") else ""
        lines.append(
            f"descubrimiento {found.get('queries', 0)} consultas, {found.get('found', 0)} "
            f"encontrados, {found.get('added', 0)} nuevos en cola{deferred}"
        )
    enrich = details.get("enrich") or {}
    if enrich:
        lines.append(
            f"enriquecimiento {enrich.get('analyzed', 0)} descargados, "
            f"{enrich.get('refreshed', 0)} actualizados, {enrich.get('unchanged', 0)} sin cambios, "
            f"{enrich.get('no_artifacts', 0)} sin artefactos, "
            f"{enrich.get('internal', 0)} con skills solo internas, "
            f"cola {details.get('frontier', 0)}"
        )
    if "velocity" in details:
        lines.append(f"tendencias {details['velocity']} repos con estrellas de la semana medidas")
    analysis = details.get("analysis") or {}
    if analysis:
        lines.append(
            f"análisis {analysis.get('analyzed', 0)} repos, {analysis.get('failed', 0)} fallidos"
        )
    for error in details.get("first_errors") or []:
        lines.append(f"error: {error}")
    return lines
