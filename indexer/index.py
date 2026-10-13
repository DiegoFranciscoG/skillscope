"""Assemble everything the static site needs into ``SiteData`` and write the JSON files.

Order (each step only uses the results of the previous ones):
collections → LSA → demand (topics, per-category, per-repo) → mentions and trend → scores →
supply and gaps → ranking and lists → files.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from analyzer.analyze import link_collections
from analyzer.lexicon import CATEGORY_LABELS, TYPE_LABELS
from analyzer.model import RepoAnalysis
from analyzer.risk import SECRET_LIKE
from analyzer.scoring import (
    Score,
    SignalInput,
    mention_weight,
    risk_level,
    score,
)
from analyzer.text import stem, tokens
from indexer import demand as demand_mod
from indexer import embeddings
from indexer.lists import Ranked, all_lists
from pipeline.catalog import CatalogRecord
from pipeline.clock import days_between, iso, parse_iso
from pipeline.jsonio import dumps, write_json
from pipeline.models import DemandItem, Mention
from pipeline.signals import SignalStore

SCHEMA_VERSION = 1
SPIKE_MIN = 1000
CANDIDATES_MAX = 5000  # queued repos published for search (~1 MB, ~250 KB gzipped)
REPO_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9._-]{1,100}$")
TOPIC = re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$")
CONTROL = re.compile(r"[\x00-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")
SERIES_PUBLISHED_DAYS = 30
DEMAND_PUBLISHED = 300
CO_LIMIT = 5
ATTRIBUTION = (
    "Preguntas de Stack Overflow (red Stack Exchange), publicadas por sus autores bajo "
    "licencia CC BY-SA 4.0. Se muestran título, autor y enlace al original."
)
SAMPLE_ATTRIBUTION = (
    "Preguntas ficticias de ejemplo: el modo sin conexión no consulta Stack Exchange y sus "
    "enlaces apuntan a example.com."
)


@dataclass(slots=True)
class Entry:
    analysis: RepoAnalysis
    score: Score
    first_seen: str
    collections: list[str]
    co: list[str]
    mentions_30d: float
    mention_counts: dict[str, int]
    trend: float
    answers: list[str]
    stars_7d: int | None = None

    @property
    def id(self) -> str:
        return self.analysis.id


@dataclass(slots=True)
class SiteData:
    build_id: str
    built_at: str
    site_url: str
    entries: list[Entry]  # published, ordered by score
    catalog_size: int
    lists: dict[str, Any]
    topics: list[demand_mod.Topic]
    gaps: list[demand_mod.Topic]
    category_demand: dict[str, float]
    demand_items: list[DemandItem]
    sources: list[dict[str, Any]]
    model: embeddings.LsaModel
    days: list[str]
    signals: SignalStore
    sample_mode: bool = False
    candidates: list[dict[str, Any]] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)


def _doc_text(analysis: RepoAnalysis) -> str:
    return f"{analysis.index_text} {' '.join(analysis.keywords)}"


def _mention_stats(
    mentions: list[Mention], now: datetime
) -> tuple[float, int, float, dict[str, int], float]:
    """Decayed weight (180 d), count, 30-day moving sum, counts by source, mention growth."""
    weight = 0.0
    window = 0.0
    counts: Counter[str] = Counter()
    last7 = prev7 = 0
    for mention in mentions:
        age = days_between(parse_iso(f"{mention.day}T00:00:00Z"), now) or 0.0
        w = mention_weight(mention.source, age, mention.engagement)
        if w <= 0:
            continue
        weight += w
        counts[mention.source] += 1
        if age <= 30:
            window += w / 2 ** (-age / 30)  # same weight without the recency decay
        if age <= 7:
            last7 += 1
        elif age <= 14:
            prev7 += 1
    growth = max(0.0, (last7 - prev7) / (prev7 + 3))
    return weight, sum(counts.values()), round(window, 3), dict(counts), growth


def star_spike(gained: int | None, stars: int) -> bool:
    """More than half of all stars arrived this week (and at least 1,000): a fact readers should
    weigh before trusting popularity, since star counts can be inflated. Not an accusation."""
    return bool(gained and gained >= SPIKE_MIN and gained * 2 > stars)


def _fresh_velocity(entry: dict[str, Any] | None, now: datetime) -> int | None:
    """Stars of the last 7 days (collector/github/stars.py) if measured in the last 2 days."""
    if not entry or entry.get("d7") is None:
        return None
    measured = parse_iso(entry.get("at"))
    if measured is None or now - measured > timedelta(days=2):
        return None
    return int(entry["d7"])


def _star_growth(
    signals: SignalStore, analysis: RepoAnalysis, now: datetime, gained: int | None = None
) -> float:
    """(stars now − stars a week ago) / (stars a week ago + 20).

    With a fresh GitHub star-history measurement the week-ago value is ``stars − gained``;
    otherwise our own daily snapshots are used (oldest day while there is less than a week).
    """
    if gained is not None:
        return gained / (max(0, analysis.meta.stars - gained) + 20)
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    recorded = signals.value_on_or_before(analysis.id, "stars", week_ago)
    if recorded is None:
        return 0.0
    return (analysis.meta.stars - recorded) / (recorded + 20)


def build(
    records: list[CatalogRecord],
    signals: SignalStore,
    *,
    site_url: str,
    now: datetime,
    sources: list[dict[str, Any]],
    excluded: set[str],
    index_max: int,
    sample_mode: bool = False,
    queue: dict[str, dict[str, Any]] | None = None,
    velocity: dict[str, dict[str, Any]] | None = None,
) -> SiteData:
    analyses = [r.analysis for r in records if r.analysis.id.lower() not in excluded]
    if sample_mode:  # offline demo: fictional repos never link to github.com
        for analysis in analyses:
            analysis.sample = True
    first_seen = {r.analysis.id: r.first_seen or iso(now) for r in records}
    linked = link_collections(analyses)

    model = embeddings.build_lsa([(a.id, _doc_text(a)) for a in analyses])
    repo_tokens = [set(tokens(_doc_text(a))) | {stem(k) for k in a.keywords} for a in analyses]

    # Only questions about working with an AI agent count as demand (indexer/demand.py).
    demand_items = [item for item in signals.demand() if demand_mod.relevant(item)]
    topics = demand_mod.cluster(demand_items)
    per_category = demand_mod.category_demand(demand_items)
    max_category = max(per_category.values(), default=0.0)
    matched, answers = demand_mod.matched_demand(model, demand_items, repo_tokens)

    mentions = signals.mentions_by_repo()
    entries: list[Entry] = []
    for index, analysis in enumerate(analyses):
        weight, count, window, by_source, mention_growth = _mention_stats(
            mentions.get(analysis.id.lower(), []), now
        )
        downloads = signals.npm_downloads(analysis.npm_package)
        if downloads is not None:
            analysis.npm_downloads = downloads
        signal_input = SignalInput(
            collections=len(linked.collections.get(analysis.id, [])),
            mention_weight=weight,
            mentions_counted=count,
            matched_demand=matched[index],
            category_demand=per_category.get(analysis.category, 0.0),
            max_category_demand=max_category,
            has_demand=bool(demand_items),
        )
        result = score(analysis, signal_input, now)
        gained = _fresh_velocity((velocity or {}).get(analysis.id.lower()), now)
        trend = 0.7 * _star_growth(signals, analysis, now, gained) + 0.3 * mention_growth
        entries.append(
            Entry(
                analysis=analysis,
                score=result,
                first_seen=first_seen.get(analysis.id, iso(now)),
                collections=sorted(linked.collections.get(analysis.id, [])),
                co=[],  # filled after ranking (needs scores)
                mentions_30d=window,
                mention_counts=by_source,
                trend=round(max(0.0, trend), 4),
                answers=answers[index][:3],
                stars_7d=gained,
            )
        )

    # "Se usan junto con eso": repos sharing the most collections, then by score.
    scores_by_id = {e.id: e.score.total for e in entries}
    for entry in entries:
        shared = linked.co_occurrence.get(entry.id, Counter())
        entry.co = sorted(shared, key=lambda r: (-shared[r], -scores_by_id.get(r, 0), r))[:CO_LIMIT]
    demand_mod.attach_supply(topics, model, repo_tokens, [e.score.total for e in entries])
    gap_topics = demand_mod.gaps(topics)

    entries.sort(key=lambda e: (-e.score.total, -e.analysis.meta.stars, e.id.lower()))
    published = entries[:index_max]
    ranked = [
        Ranked(
            id=e.id,
            type=e.analysis.type,
            category=e.analysis.category,
            total=e.score.total,
            quality=e.score.get("quality"),
            adoption=e.score.get("adoption"),
            social=e.score.get("social"),
            utility=e.score.get("utility"),
            penalty=e.analysis.risk_penalty,
            stars=e.analysis.meta.stars,
            mentions_30d=e.mentions_30d,
            trend=e.trend,
            created_days=days_between(parse_iso(e.analysis.meta.created_at), now),
        )
        for e in published
    ]
    published_ids = [e.id for e in published]
    position = {repo_id: i for i, repo_id in enumerate(model.ids)}
    rows = [position[repo_id] for repo_id in published_ids]
    published_model = embeddings.LsaModel(
        ids=published_ids,
        terms=model.terms,
        idf=model.idf,
        term_vectors=model.term_vectors,
        doc_vectors=model.doc_vectors[rows] if model.dims else np.zeros((len(rows), 0)),
    )
    days = [
        (now - timedelta(days=offset)).strftime("%Y-%m-%d")
        for offset in range(SERIES_PUBLISHED_DAYS - 1, -1, -1)
    ]
    content_hash = hashlib.sha256(
        dumps([(e.id, e.score.total, e.analysis.meta.head_oid) for e in published]).encode()
    ).hexdigest()[:7]
    return SiteData(
        build_id=f"{now.strftime('%Y%m%dT%H%M%SZ')}-{content_hash}",
        built_at=iso(now),
        site_url=site_url,
        entries=published,
        catalog_size=len(entries),
        lists=all_lists(ranked, per_category),
        topics=topics,
        gaps=gap_topics,
        category_demand=per_category,
        demand_items=demand_items,
        sources=sources,
        model=published_model,
        days=days,
        signals=signals,
        sample_mode=sample_mode,
        candidates=candidates_from(queue or {}, {e.id.lower() for e in published} | excluded),
    )


# ---------------------------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------------------------
def index_item(entry: Entry, now: datetime) -> dict[str, Any]:
    a = entry.analysis
    meta = a.meta
    return {
        "id": a.id,
        "owner": meta.owner,
        "name": meta.name,
        "type": a.type,
        "category": a.category,
        "categories": a.categories,
        "cause": a.cause,
        "score": entry.score.total,
        "components": {c.id: c.points for c in entry.score.components},
        "risk": {
            "level": risk_level(a.risk_penalty),
            "penalty": a.risk_penalty,
            "flags": [f.id for f in a.risks],
        },
        "stars": meta.stars,
        "forks": meta.forks,
        "pushed_at": meta.pushed_at,
        "license": meta.license,
        "summary": a.summary(now),
        "keywords": a.keywords[:16],
        "install": a.install.one_liner,
        "counts": {k: v for k, v in a.counts.items() if v},
        "first_seen": entry.first_seen,
        "mentions_30d": entry.mentions_30d,
        "trend": entry.trend,
        "stars_7d": entry.stars_7d,
        "star_spike": star_spike(entry.stars_7d, entry.analysis.meta.stars),
        "co": entry.co,
        "sample": a.sample,
    }


def candidates_from(queue: dict[str, dict[str, Any]], skip: set[str]) -> list[dict[str, Any]]:
    """Queued repositories not analyzed yet, so a search never stops at the published index.

    Everything here came from the GitHub search API, so it is treated as untrusted text: only
    valid ``owner/repo`` ids, control characters removed, secrets redacted, short fields.
    """
    ordered = sorted(queue.values(), key=lambda e: (-float(e.get("priority", 0)), str(e["id"])))
    out: list[dict[str, Any]] = []
    for entry in ordered:
        repo_id = str(entry.get("id", ""))
        if repo_id.lower() in skip or not REPO_ID.match(repo_id):
            continue
        description = CONTROL.sub(" ", str(entry.get("description") or ""))
        out.append(
            {
                "id": repo_id,
                "d": SECRET_LIKE.sub("[secreto oculto]", description).strip()[:300],
                "t": [t for t in entry.get("topics", []) if TOPIC.match(str(t))][:8],
                "l": CONTROL.sub("", str(entry.get("language") or ""))[:40],
                "s": int(entry.get("stars") or 0),
                "p": entry.get("pushed_at"),
            }
        )
        if len(out) >= CANDIDATES_MAX:
            break
    return out


def _redacted(flag: dict[str, Any]) -> dict[str, Any]:
    """Defence in depth: evidence cached by an older analyzer is redacted again on output."""
    for evidence in flag.get("evidence", []):
        evidence["snippet"] = SECRET_LIKE.sub("[secreto oculto]", str(evidence.get("snippet", "")))
    return flag


def detail_item(entry: Entry, data: SiteData, now: datetime) -> dict[str, Any]:
    a = entry.analysis
    meta = a.meta
    signals = data.signals
    return {
        "id": a.id,
        "what": a.what(now),
        "when": a.when,
        "install": a.install.to_dict(),
        "risks": [_redacted(r.to_dict()) for r in a.risks],
        "score": entry.score.to_dict(),
        "artifacts": [x.public() for x in a.artifacts[:50]],
        "tools": a.tools,
        "readme_lang": a.readme_lang,
        "collections": entry.collections,
        "co": entry.co,
        "topics": meta.topics,
        "category_terms": a.category_terms,
        "answers": entry.answers,
        "signals": {
            "stars": signals.series(a.id, "stars", data.days),
            "mentions": entry.mention_counts,
        },
        "links": {
            "repo": None if a.sample else meta.url,
            "license": None if a.sample or not meta.license else f"{meta.url}#license",
        },
        "archived": meta.archived,
        "created_at": meta.created_at,
    }


def _totals(data: SiteData) -> dict[str, Any]:
    by_type: Counter[str] = Counter()
    by_category: Counter[str] = Counter()
    by_risk: Counter[str] = Counter()
    artifacts: Counter[str] = Counter()
    for entry in data.entries:
        a = entry.analysis
        by_type[a.type] += 1
        by_category[a.category] += 1
        by_risk[str(risk_level(a.risk_penalty))] += 1
        for key in ("skills", "plugins", "commands", "agents", "hooks"):
            artifacts[key] += a.counts.get(key, 0)
    return {
        "repos": len(data.entries),
        "catalog": data.catalog_size,
        "queue": len(data.candidates),
        "artifacts": dict(artifacts),
        "by_type": dict(by_type),
        "by_category": dict(by_category),
        "by_risk": dict(by_risk),
    }


def _short_hash(payload: str | bytes) -> str:
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    return hashlib.sha256(raw).hexdigest()[:12]


def write(data: SiteData, out_dir: Path, now: datetime) -> dict[str, str]:
    """Write every JSON file of ``out_dir/data``; returns the versioned file map."""
    target = out_dir / "data"
    files: dict[str, str] = {}

    shards: dict[str, dict[str, Any]] = defaultdict(dict)
    for entry in data.entries:
        shards[entry.analysis.category][entry.id] = detail_item(entry, data, now)
    for category, items in sorted(shards.items()):
        payload = {"schema_version": SCHEMA_VERSION, "build_id": data.build_id, "items": items}
        write_json(target / "detail" / f"{category}.json", payload)
        files[f"detail:{category}"] = f"data/detail/{category}.json?v={_short_hash(dumps(payload))}"

    bin_hash, meta_hash = embeddings.write(data.model, target)
    files["embeddings"] = f"data/embeddings.bin?v={bin_hash}"
    files["embeddings_meta"] = f"data/embeddings.json?v={meta_hash}"

    queue_payload = {"schema_version": SCHEMA_VERSION, "items": data.candidates}
    write_json(target / "candidates.json", queue_payload)
    files["candidates"] = f"data/candidates.json?v={_short_hash(dumps(queue_payload))}"

    published = {e.id for e in data.entries}
    se_items = sorted(
        (i for i in data.demand_items if i.title),
        key=lambda i: (i.created_at, i.id),
        reverse=True,
    )[:DEMAND_PUBLISHED]
    topic_of = {f"{i.source}:{i.id}": t.id for t in data.topics for i in t.items}
    demand_payload = {
        "schema_version": SCHEMA_VERSION,
        "build_id": data.build_id,
        "attribution": SAMPLE_ATTRIBUTION if data.sample_mode else ATTRIBUTION,
        "sample": data.sample_mode,
        "items": [
            {
                "key": f"{i.source}:{i.id}",
                "source": i.source,
                "title": i.title,
                "url": i.url,
                "author": i.author,
                "author_url": i.author_url,
                "created_at": i.created_at,
                "answered": i.answered,
                "tags": i.tags,
                "topic": topic_of.get(f"{i.source}:{i.id}"),
            }
            for i in se_items
        ],
        "aggregates": [
            {
                "source": i.source,
                "category": i.id.split(":")[0],
                "count": i.count,
                "day": i.created_at[:10],
            }
            for i in data.demand_items
            if not i.title
        ],
        "topics": [
            {
                "id": t.id,
                "label": t.label,
                "keywords": t.keywords,
                "subjects": t.subjects,
                "specific": t.specific,
                "category": t.category,
                "demand": t.demand,
                "questions": len(t.items),
                "supply": [r for r in t.supply if r in published][:10],
                "examples": [f"{i.source}:{i.id}" for i in t.items if i.title][:3],
            }
            for t in data.topics[:100]
        ],
        "gaps": [
            {
                "topic": t.id,
                "label": t.label,
                "keywords": t.keywords,
                "category": t.category,
                "demand": t.demand,
                "questions": len(t.items),
                "examples": [f"{i.source}:{i.id}" for i in t.items if i.title][:3],
            }
            for t in data.gaps[:50]
        ],
        "categories": [
            {"category": c, "label": CATEGORY_LABELS.get(c, c), "demand": round(v, 2)}
            for c, v in sorted(data.category_demand.items(), key=lambda kv: -kv[1])
        ],
    }
    write_json(target / "demand.json", demand_payload)
    files["demand"] = f"data/demand.json?v={_short_hash(dumps(demand_payload))}"

    series_payload = {
        "schema_version": SCHEMA_VERSION,
        "build_id": data.build_id,
        "days": data.days,
        "repos": {
            e.id: {
                "stars": data.signals.series(e.id, "stars", data.days),
                "forks": data.signals.series(e.id, "forks", data.days),
                "commits_30d": data.signals.series(e.id, "commits", data.days),
            }
            for e in data.entries
        },
        "mentions": {e.id: e.mention_counts for e in data.entries if e.mention_counts},
    }
    write_json(target / "signals.json", series_payload)
    files["signals"] = f"data/signals.json?v={_short_hash(dumps(series_payload))}"

    index_payload = {
        "schema_version": SCHEMA_VERSION,
        "build_id": data.build_id,
        "built_at": data.built_at,
        "site_url": data.site_url,
        "totals": _totals(data),
        "sources": data.sources,
        "labels": {"types": TYPE_LABELS, "categories": CATEGORY_LABELS},
        "files": files,
        "lists": data.lists,
        "gaps": len(data.gaps),
        "items": [index_item(e, now) for e in data.entries],
    }
    write_json(target / "index.json", index_payload)
    data.files = files
    return files
