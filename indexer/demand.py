"""Demand topics and ecosystem gaps (docs/algoritmo.md §1.5 and §2).

Questions are grouped with their *own* TF-IDF vocabulary, not with the repositories' LSA
space: a gap is precisely a topic the repositories do not cover, so their vocabulary
cannot represent it.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from analyzer.taxonomy import classify_category
from analyzer.text import keywords, stem, tokens
from indexer.embeddings import LsaModel
from pipeline.models import DemandItem

TOPIC_THRESHOLD = 0.3
MATCH_THRESHOLD = 0.35
SUPPLY_MIN_SCORE = 40
GAP_MIN_DEMAND = 2.0


def item_weight(item: DemandItem) -> float:
    if item.source == "reddit":
        return 0.8 * item.count
    return 0.5 if item.answered else 1.0


@dataclass(slots=True)
class Topic:
    id: str
    label: str
    keywords: list[str]
    category: str
    items: list[DemandItem] = field(default_factory=list)
    demand: float = 0.0
    supply: list[str] = field(default_factory=list)


def _vectors(items: list[DemandItem]) -> NDArray[np.float64]:
    docs = [tokens(i.text) for i in items]
    vocab = sorted({t for doc in docs for t in doc})
    index = {t: n for n, t in enumerate(vocab)}
    df = Counter(t for doc in docs for t in set(doc))
    total = len(docs)
    matrix = np.zeros((len(docs), len(vocab)))
    for row, doc in enumerate(docs):
        for term, count in Counter(doc).items():
            idf = math.log((total + 1) / (df[term] + 1)) + 1
            matrix[row, index[term]] = (1 + math.log(count)) * idf
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def cluster(items: list[DemandItem]) -> list[Topic]:
    """Greedy, deterministic grouping in date order (cosine ≥ 0.3 to the topic centroid)."""
    ordered = sorted(items, key=lambda i: (i.created_at, i.source, i.id))
    if not ordered:
        return []
    vectors = _vectors(ordered)
    groups: list[list[int]] = []
    centroids: list[NDArray[np.float64]] = []
    for row, vector in enumerate(vectors):
        best, best_sim = -1, 0.0
        for g, centroid in enumerate(centroids):
            sim = float(vector @ centroid)
            if sim > best_sim:
                best, best_sim = g, sim
        if best >= 0 and best_sim >= TOPIC_THRESHOLD:
            groups[best].append(row)
            merged = vectors[groups[best]].sum(axis=0)
            centroids[best] = merged / (np.linalg.norm(merged) or 1.0)
        else:
            groups.append([row])
            centroids.append(vector)
    topics: list[Topic] = []
    for members in groups:
        member_items = [ordered[m] for m in members]
        words: Counter[str] = Counter()
        for item in member_items:
            words.update(dict.fromkeys(keywords(item.text), 1))
        top = [w for w, _ in sorted(words.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
        category = classify_category([(" ".join(i.text for i in member_items), 1.0)]).primary
        topic_id = "-".join(top) or f"tema-{len(topics) + 1}"
        topics.append(
            Topic(
                id=topic_id,
                label=", ".join(top),
                keywords=top,
                category=category,
                items=member_items,
                demand=round(sum(item_weight(i) for i in member_items), 2),
            )
        )
    return sorted(topics, key=lambda t: (-t.demand, t.id))


def category_demand(items: list[DemandItem]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for item in items:
        totals[classify_category([(item.text, 1.0)]).primary] += item_weight(item)
    return dict(totals)


def matched_demand(
    model: LsaModel, items: list[DemandItem], repo_tokens: list[set[str]]
) -> list[float]:
    """For each repository: Σ weight of questions it answers (LSA cos ≥ 0.35 + shared stem)."""
    result = [0.0] * len(model.ids)
    if not items or not model.dims:
        return result
    for item in items:
        vector = model.project(item.text)
        if not vector.any():
            continue
        sims = model.similarities(vector)
        stems = {stem(w) for w in keywords(item.text)}
        weight = item_weight(item)
        for index in np.nonzero(sims >= MATCH_THRESHOLD)[0]:
            if stems & repo_tokens[int(index)]:
                result[int(index)] += weight
    return result


def attach_supply(
    topics: list[Topic],
    model: LsaModel,
    repo_tokens: list[set[str]],
    scores: list[int],
) -> None:
    """Supply of a topic: repos with score ≥ 40 that share most of its keywords or its meaning."""
    for topic in topics:
        stems = {stem(w) for w in topic.keywords}
        vector = model.project(" ".join(i.text for i in topic.items))
        sims = model.similarities(vector)
        supply: list[str] = []
        for index, repo_id in enumerate(model.ids):
            if scores[index] < SUPPLY_MIN_SCORE:
                continue
            overlap = len(stems & repo_tokens[index])
            by_words = bool(stems) and overlap >= max(1, math.ceil(len(stems) / 2))
            by_meaning = float(sims[index]) >= MATCH_THRESHOLD and overlap >= 1
            if by_words or by_meaning:
                supply.append(repo_id)
        topic.supply = supply


def gaps(topics: list[Topic]) -> list[Topic]:
    return [t for t in topics if t.demand >= GAP_MIN_DEMAND and not t.supply]
