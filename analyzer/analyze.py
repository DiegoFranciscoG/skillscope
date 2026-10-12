"""Turn repository snapshots into analyses: artifacts, type, category, cause, install,
risks, own summary and the collection graph (marketplaces and awesome lists)."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from analyzer.copyguard import overlaps
from analyzer.detect import layout
from analyzer.install import SAFE_PACKAGE, build_install, marketplace_install
from analyzer.language import detect
from analyzer.model import Artifact, MarketplaceEntry, RepoAnalysis
from analyzer.risk import RiskInput, scan
from analyzer.summary import build_lead, build_when, static_facts
from analyzer.taxonomy import (
    classify_category,
    classify_cause,
    determine_type,
    github_links,
    is_mcp_package,
)
from analyzer.text import fold, keywords, stem, words
from analyzer.validate import (
    mcp_servers,
    validate_agent,
    validate_command,
    validate_hooks,
    validate_marketplace,
    validate_plugin_manifest,
    validate_skill,
)
from pipeline.models import RepoSnapshot
from pipeline.optout import has_optout_topic

EXAMPLES_RE = re.compile(r"^#{1,4}\s*(examples?|ejemplos?|usage|uso|demo|how to use)\b", re.M)
INSTALL_RE = re.compile(
    r"/plugin\s+(marketplace\s+add|install)|claude\s+plugin|claude\s+mcp\s+add|\.claude/(skills|agents|commands)"
    r"|\binstall(ation|ing)?\b|\binstala(cion|r)?\b|plugin-dir"
)


@dataclass(slots=True)
class AnalysisSet:
    analyses: list[RepoAnalysis]
    collections: dict[str, list[str]] = field(default_factory=dict)
    co_occurrence: dict[str, Counter[str]] = field(default_factory=dict)


def _readme_head(readme: str) -> str:
    """Headings and first paragraphs only: enough to classify, never republished."""
    return readme[:2500]


def _keywords(fields: Iterable[tuple[str, float]], limit: int = 12) -> list[str]:
    """Most weighted descriptive words, one surface form per stem (secret/secrets → secret)."""
    counts: defaultdict[str, float] = defaultdict(float)
    surface: dict[str, str] = {}
    first_seen: dict[str, int] = {}
    for text, weight in fields:
        for word in keywords(text):
            key = stem(word)
            counts[key] += weight
            if key not in surface or len(word) < len(surface[key]):
                surface[key] = word
            first_seen.setdefault(key, len(first_seen))
    ranked = sorted(counts, key=lambda k: (-counts[k], first_seen[k]))
    return [surface[k] for k in ranked[:limit]]


def _npm_package(repo_type: str, package_json: str | None) -> str | None:
    """Published npm name of an MCP server (adoption factor a4 uses its downloads)."""
    if repo_type != "mcp_server" or not package_json:
        return None
    try:
        data = json.loads(package_json)
    except json.JSONDecodeError:
        return None
    name = data.get("name") if isinstance(data, dict) else None
    if not isinstance(name, str) or data.get("private") or not SAFE_PACKAGE.match(name):
        return None
    return name


def analyze_snapshot(snapshot: RepoSnapshot, now: datetime) -> RepoAnalysis | None:
    meta = snapshot.meta
    if has_optout_topic(meta.topics):
        return None
    lay = layout(snapshot.tree)
    files = snapshot.files
    readme = files.get(lay.readme or "", "")

    artifacts: list[Artifact] = []
    for path in lay.skills:
        if path in files:
            artifacts.append(validate_skill(path, files[path]))
    plugin_data = [
        validate_plugin_manifest(p, files[p]) for p in lay.plugin_manifests if p in files
    ]
    artifacts += [p.artifact for p in plugin_data]
    marketplace = None
    if lay.marketplace and lay.marketplace in files:
        marketplace = validate_marketplace(lay.marketplace, files[lay.marketplace], meta.owner)
        artifacts.append(marketplace.artifact)
    for path in lay.agents:
        if path in files:
            artifacts.append(validate_agent(path, files[path]))
    for path in lay.commands:
        if path in files:
            artifacts.append(validate_command(path, files[path]))
    hook_commands: list[tuple[str, str]] = []
    for path in [*lay.hooks, *lay.settings]:
        if path in files:
            artifact, commands = validate_hooks(path, files[path])
            if path.endswith("hooks.json") or commands:
                artifacts.append(artifact)
            hook_commands += [(path, c) for c in commands]
    servers: list[tuple[str, dict[str, object]]] = []
    for path in lay.mcp:
        if path in files:
            artifact, found = mcp_servers(path, files[path])
            artifacts.append(artifact)
            servers += [(path, s) for s in found]

    package_json = files.get(lay.package_json or "")
    pyproject = files.get(lay.pyproject or "")
    links = github_links(readme, exclude=meta.id)
    topics_lower = [t.lower() for t in meta.topics]
    looks_awesome = "awesome" in meta.name.lower() or any("awesome" in t for t in topics_lower)
    entries: list[MarketplaceEntry] = marketplace.entries if marketplace else []
    repo_type = determine_type(
        is_template=meta.is_template,
        has_marketplace=marketplace is not None,
        has_plugin=bool(lay.plugin_manifests),
        has_skills=bool(lay.skills),
        is_mcp=is_mcp_package(package_json, pyproject),
        has_agents=bool(lay.agents),
        has_commands=bool(lay.commands),
        has_hooks=bool(hook_commands or lay.hooks),
        looks_awesome=looks_awesome,
        link_count=len(links),
    )

    descriptions = " ".join(a.description for a in artifacts if a.description)
    names = " ".join(a.name.replace("-", " ") for a in artifacts if a.kind in {"skill", "agent"})
    entry_names = " ".join(e.name.replace("-", " ") for e in entries)
    fields = [
        (meta.name.replace("-", " ").replace("_", " "), 3.0),
        (" ".join(t.replace("-", " ") for t in meta.topics), 2.0),
        (f"{descriptions} {names} {entry_names} {meta.description}", 1.0),
        (_readme_head(readme), 0.5),
    ]
    category = classify_category(fields)
    cause = classify_cause(fields)
    kw = _keywords(fields[:3])

    counts = {
        "skills": len(lay.skills),
        "plugins": len(entries) if marketplace else len(lay.plugin_manifests),
        "commands": len(lay.commands),
        "agents": len(lay.agents),
        "hooks": len(hook_commands),
        "mcp_servers": len(servers),
        "links": len(links) if repo_type == "awesome_list" else 0,
    }
    tools = sorted({t for a in artifacts for t in a.tools if t != "bypassPermissions"})
    markdown_paths = [a.path for a in artifacts if a.kind in {"skill", "agent", "command"}]
    risks = scan(
        RiskInput(
            files=files,
            readme=readme,
            markdown_paths=markdown_paths,
            script_paths=list(lay.scripts),
            exec_paths=list(lay.exec_scripts),
            hook_commands=hook_commands,
            mcp_servers=servers,
            artifacts=artifacts,
            license=meta.license,
            marketplace_entries=entries,
            marketplace_path=lay.marketplace,
        )
    )
    install = build_install(
        repo_id=meta.id,
        repo_type=repo_type,
        marketplace_name=marketplace.name if marketplace else None,
        marketplace_installable=bool(marketplace and marketplace.installable),
        marketplace_plugins=[e.name for e in entries],
        artifacts=artifacts,
        package_json=package_json,
        pyproject=pyproject,
    )

    skills = [a for a in artifacts if a.kind == "skill"]
    described = [a for a in artifacts if a.kind in {"skill", "agent"} and a.description]
    analyzable = [
        a
        for a in artifacts
        if a.kind in {"skill", "plugin_manifest", "marketplace_manifest", "agent"}
    ]
    folded_readme = fold(readme[:50_000])
    facts = {
        "analyzable": len(analyzable),
        "valid": sum(1 for a in analyzable if a.valid),
        "described": len(described),
        "with_when": sum(1 for a in described if a.has_when),
        "any_description": bool(descriptions or meta.description),
        "skills_measured": len(skills),
        "skills_short": sum(1 for a in skills if a.lines <= 500),
        "all_very_short": bool(skills) and all(a.lines <= 200 for a in skills),
        "support_files": bool(lay.support_dirs),
        "examples": lay.has_examples
        or bool(EXAMPLES_RE.search(folded_readme))
        or any(EXAMPLES_RE.search(fold(files.get(a.path, "")[:20_000])) for a in skills),
        "readme": bool(readme),
        "readme_install": bool(readme) and bool(INSTALL_RE.search(folded_readme)),
        "tests_or_ci": lay.has_tests or lay.has_ci,
        "tree_truncated": snapshot.tree_truncated,
    }

    source_text = "\n".join([readme, descriptions, meta.description])
    name_words = {stem(w) for w in words(f"{meta.owner} {meta.name}".replace("-", " "))}
    summary_keywords = [w for w in kw if stem(w) not in name_words]
    lead = build_lead(
        repo_type=repo_type,
        category=category.primary,
        cause=cause.primary,
        counts=counts,
        links=len(links),
        keywords=summary_keywords,
    )
    if overlaps(lead, source_text):  # pragma: no cover - templates make this unreachable
        lead = build_lead(
            repo_type=repo_type,
            category=category.primary,
            cause=cause.primary,
            counts=counts,
            links=len(links),
            keywords=[],
        )
    included = [a.name for a in artifacts if a.kind in {"skill", "agent"}][:5]
    if repo_type == "marketplace" and entries:
        included = [e.name for e in entries][:5]
    when = [w for w in build_when(category.primary, artifacts) if not overlaps(w, source_text)]

    index_text = " ".join(
        [
            meta.name.replace("-", " "),
            " ".join(meta.topics),
            descriptions,
            names,
            entry_names,
            meta.description,
        ]
    )
    return RepoAnalysis(
        meta=meta,
        sample=snapshot.sample,
        type=repo_type,
        category=category.primary,
        categories=category.secondary,
        cause=cause.primary,
        category_terms=category.terms,
        artifacts=artifacts,
        counts=counts,
        tools=tools,
        readme_lang=detect(readme),
        keywords=kw,
        marketplace_name=marketplace.name if marketplace else None,
        marketplace_entries=entries,
        list_links=links if repo_type == "awesome_list" else [],
        install=install,
        risks=risks,
        facts=facts,
        index_text=index_text,
        summary_lead=lead,
        summary_facts=static_facts(tools, meta.license),
        included=included,
        when=when,
        npm_package=snapshot.npm_package or _npm_package(repo_type, package_json),
        npm_downloads=snapshot.npm_downloads,
        source_text=source_text,
    )


def link_collections(analyses: list[RepoAnalysis]) -> AnalysisSet:
    """Collection graph (marketplaces and awesome lists), co-occurrence and install fixes."""
    by_id = {a.id.lower(): a for a in analyses}
    members: dict[str, list[str]] = {}
    for analysis in analyses:
        if analysis.type == "marketplace":
            refs = [e.repo for e in analysis.marketplace_entries if e.repo]
        elif analysis.type == "awesome_list":
            refs = analysis.list_links
        else:
            continue
        unique: list[str] = []
        for ref in refs:
            key = str(ref).lower()
            if key != analysis.id.lower() and key in by_id and key not in unique:
                unique.append(key)
        members[analysis.id] = [by_id[k].id for k in unique]

    collections: dict[str, list[str]] = defaultdict(list)
    co: dict[str, Counter[str]] = defaultdict(Counter)
    for collection_id, repo_ids in members.items():
        for repo_id in repo_ids:
            collections[repo_id].append(collection_id)
            for other in repo_ids:
                if other != repo_id:
                    co[repo_id][other] += 1

    # A plugin without its own marketplace can still be installed by name through a
    # marketplace in the index that lists it.
    for analysis in analyses:
        if analysis.type != "plugin" or analysis.install.kind != "plugin_dir":
            continue
        for collection_id in collections.get(analysis.id, []):
            market = by_id[collection_id.lower()]
            if market.type != "marketplace" or not market.marketplace_name:
                continue
            entry = next(
                (
                    e
                    for e in market.marketplace_entries
                    if (e.repo or "").lower() == analysis.id.lower()
                ),
                None,
            )
            if entry is None:
                continue
            install = marketplace_install(market.id, market.marketplace_name, [entry.name])
            if install:
                install.note = f"Se instala desde el marketplace {market.id}."
                analysis.install = install
                break
    return AnalysisSet(analyses, dict(collections), dict(co))


def analyze_all(snapshots: Iterable[RepoSnapshot], now: datetime) -> AnalysisSet:
    analyses = [a for a in (analyze_snapshot(s, now) for s in snapshots) if a is not None]
    return link_collections(analyses)
