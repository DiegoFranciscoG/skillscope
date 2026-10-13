"""Type, category and cause assignment (docs/modelo-datos.md §3, docs/algoritmo.md §3.4)."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache

from analyzer.lexicon import CATEGORY_TERMS, CAUSE_TERMS
from analyzer.text import LEXICON, stem, tokens

MCP_JS_RE = re.compile(r'"@modelcontextprotocol/sdk"\s*:')
MCP_PY_RE = re.compile(r"""["'](?:mcp|fastmcp)(?:\[[^\]]*\])?\s*(?:[=<>~!]=?[^"']*)?["']""")
# Owners: GitHub logins use letters, digits and hyphens. The underscore is accepted only so the
# fictional demo owners (demo_*) parse; GitHub never allows it, so they cannot match a real account.
GITHUB_LINK_RE = re.compile(
    r"https?://github\.com/([A-Za-z0-9](?:[A-Za-z0-9_-]{0,38}))/([A-Za-z0-9._-]{1,100})"
)
NON_REPO_OWNERS = frozenset(
    {"orgs", "topics", "sponsors", "marketplace", "features", "settings", "apps", "about"}
)


@dataclass(slots=True)
class Classification:
    primary: str
    secondary: list[str]
    terms: list[str]


@lru_cache(maxsize=32)
def _stemmed(kind: str) -> dict[str, dict[str, float]]:
    source = CATEGORY_TERMS if kind == "category" else CAUSE_TERMS
    out: dict[str, dict[str, float]] = {}
    for label, terms in source.items():
        stemmed: dict[str, float] = {}
        for term, weight in terms.items():
            key = stem(LEXICON.get(term, term))
            stemmed[key] = max(stemmed.get(key, 0.0), float(weight))
        out[label] = stemmed
    return out


def weighted_tokens(fields: list[tuple[str, float]]) -> dict[str, float]:
    counts: defaultdict[str, float] = defaultdict(float)
    for text, weight in fields:
        for token in tokens(text):
            counts[token] += weight
    return dict(counts)


def _classify(counts: dict[str, float], kind: str, default: str) -> Classification:
    scores: dict[str, float] = {}
    evidence: dict[str, list[tuple[float, str]]] = {}
    for label, terms in _stemmed(kind).items():
        total = 0.0
        hits: list[tuple[float, str]] = []
        for token, freq in counts.items():
            weight = terms.get(token)
            if weight:
                # Repetition helps, but with diminishing returns.
                contribution = weight * min(freq, 3.0)
                total += contribution
                hits.append((contribution, token))
        if total > 0:
            scores[label] = total
            evidence[label] = sorted(hits, key=lambda h: (-h[0], h[1]))
    if not scores:
        return Classification(default, [], [])
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    primary, best = ranked[0]
    secondary = [label for label, value in ranked[1:3] if value >= 0.5 * best]
    return Classification(primary, secondary, [t for _, t in evidence[primary][:6]])


def classify_category(fields: list[tuple[str, float]]) -> Classification:
    return _classify(weighted_tokens(fields), "category", "development")


def classify_cause(fields: list[tuple[str, float]]) -> Classification:
    return _classify(weighted_tokens(fields), "cause", "automate")


def is_mcp_package(package_json: str | None, pyproject: str | None) -> bool:
    if package_json and MCP_JS_RE.search(package_json):
        return True
    return bool(pyproject and MCP_PY_RE.search(pyproject))


def github_links(text: str, exclude: str | None = None) -> list[str]:
    """Distinct ``owner/repo`` links in a README, in order of appearance."""
    seen: dict[str, str] = {}
    for match in GITHUB_LINK_RE.finditer(text or ""):
        owner, name = match.group(1), match.group(2)
        name = name.removesuffix(".git").rstrip(".")
        if owner.lower() in NON_REPO_OWNERS or not name or name.startswith("."):
            continue
        repo_id = f"{owner}/{name}"
        key = repo_id.lower()
        if exclude and key == exclude.lower():
            continue
        seen.setdefault(key, repo_id)
    return list(seen.values())


def determine_type(
    *,
    is_template: bool,
    has_marketplace: bool,
    has_plugin: bool,
    has_skills: bool,
    is_mcp: bool,
    has_agents: bool,
    has_commands: bool,
    has_hooks: bool,
    looks_awesome: bool,
    link_count: int,
) -> str:
    """First matching rule wins (docs/modelo-datos.md §3)."""
    if is_template:
        return "template"
    if has_marketplace:
        return "marketplace"
    if looks_awesome and link_count >= 10:
        return "awesome_list"
    if has_plugin:
        return "plugin"
    if has_skills:
        return "skill"
    if is_mcp:
        return "mcp_server"
    if has_agents:
        return "agent"
    if has_commands:
        return "command"
    if has_hooks:
        return "hook"
    if link_count >= 10:
        return "awesome_list"
    return "skill"
