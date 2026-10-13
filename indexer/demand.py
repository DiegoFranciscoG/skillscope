"""Demand topics and ecosystem gaps (docs/algoritmo.md §1.5 and §2).

Questions are grouped with their *own* TF-IDF vocabulary, not with the repositories' LSA
space: a gap is precisely a topic the repositories do not cover, so their vocabulary
cannot represent it.
"""

from __future__ import annotations

import math
import re
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
# Both shares are measured on the live data of each build, never on a fixed list:
GENERIC_SHARE = (
    0.25  # a tag a quarter of the repos cover ("python", "vs-code") says nothing specific
)
CONTEXT_SHARE = (
    0.10  # a tag present in a tenth of the topics is context (IDE, language), not the need
)
MIN_CORPUS = 20  # below this many repos/topics the shares are not meaningful and are not applied
AGENT_CONTEXT = re.compile(
    r"\b(claude|anthropic|mcp|model context protocol|llms?|copilot|chatgpt|openai|gpt-?\d"
    r"|agentic|codex|gemini|sub-?agents?)\b"
    r"|(?<!user )(?<!user-)(?<!ssh )(?<!ssh-)(?<!build )\bagents?\b",  # not user/ssh/CI agents
    re.IGNORECASE,
)
GENERIC_TAGS = frozenset(
    {
        "claude-code",
        "claude",
        "anthropic-claude",
        "claude-ai",
        "ai",
        "agent",
        "agents",
        "ai-agent",
        "llm",
        "large-language-model",
        "model-context-protocol",
        "mcp",
        "artificial-intelligence",
        "github-copilot",
        "chatgpt",
        "openai",
        "openai-api",
        "agent-skills",
    }
)


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
    subjects: list[str] = field(default_factory=list)  # question tags that define what is asked
    specific: list[str] = field(default_factory=list)  # subjects that are not generic context


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
        tags = [
            t
            for t in dict.fromkeys(tag for i in member_items for tag in i.tags)
            if t.lower() not in GENERIC_TAGS
        ][:3]
        label_terms = tags or top
        topic_id = "-".join(label_terms) or f"tema-{len(topics) + 1}"
        topics.append(
            Topic(
                id=topic_id,
                label=", ".join(label_terms),
                keywords=top,
                category=category,
                items=member_items,
                demand=round(sum(item_weight(i) for i in member_items), 2),
                subjects=subjects_of(member_items, top),
            )
        )
    return sorted(topics, key=lambda t: (-t.demand, t.id))


def relevant(item: DemandItem) -> bool:
    """Demand must be about working with an AI agent. Free-text search also returns questions
    that never mention one, so keep those with an agent tag or an agent term in the title."""
    if any(tag.lower() in GENERIC_TAGS for tag in item.tags):
        return True
    return bool(AGENT_CONTEXT.search(item.title or item.text))


def subjects_of(items: list[DemandItem], fallback: list[str]) -> list[str]:
    """What a topic is about: the question tags (curated by the community), whole and in order,
    minus tags that only say the question involves an AI agent. Without tags, its keywords."""
    found: list[str] = []
    for item in items:
        for tag in item.tags:
            tag = tag.lower()
            if tag not in GENERIC_TAGS and tag not in found:
                found.append(tag)
    return found or [stem(w) for w in fallback]


def _terms(subject: str) -> frozenset[str]:
    """Stems a repository must contain to cover a tag ("spring-ai" needs "spring" and "ai")."""
    return frozenset(tokens(subject.replace("-", " "))) or frozenset({subject})


def category_demand(items: list[DemandItem]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for item in items:
        totals[classify_category([(item.text, 1.0)]).primary] += item_weight(item)
    return dict(totals)


def matched_demand(
    model: LsaModel, items: list[DemandItem], repo_tokens: list[set[str]]
) -> tuple[list[float], list[list[str]]]:
    """Per repository: Σ weight of questions it answers (LSA cos ≥ 0.35 + shared stem) and
    the keys of the displayable questions it answers (Stack Exchange, with attribution)."""
    weights = [0.0] * len(model.ids)
    matches: list[list[str]] = [[] for _ in model.ids]
    if not items or not model.dims:
        return weights, matches
    for item in items:
        vector = model.project(item.text)
        if not vector.any():
            continue
        sims = model.similarities(vector)
        stems = {stem(w) for w in keywords(item.text)}
        weight = item_weight(item)
        for index in np.nonzero(sims >= MATCH_THRESHOLD)[0]:
            position = int(index)
            if stems & repo_tokens[position]:
                weights[position] += weight
                if item.title:
                    matches[position].append(f"{item.source}:{item.id}")
    return weights, matches


def attach_supply(
    topics: list[Topic],
    model: LsaModel,
    repo_tokens: list[set[str]],
    scores: list[int],
) -> None:
    """Supply of a topic: repos with score ≥ 40 that cover at least half of its specific subjects.

    "Code review in ABAP" is not covered by a generic code-review skill: it needs ``abap`` too.
    A subject is specific unless the data says it is context: a tag that a quarter of the repos
    cover or that appears in a tenth of the topics. A topic with no specific subject is too
    vague to be a gap.
    """
    total = len(model.ids)
    covered: dict[str, set[int]] = {}

    def covering(subject: str) -> set[int]:
        if subject not in covered:
            terms = _terms(subject)
            covered[subject] = {i for i, have in enumerate(repo_tokens) if terms <= have}
        return covered[subject]

    in_topics = Counter(s for topic in topics for s in set(topic.subjects))

    def specific(subject: str) -> bool:
        if total >= MIN_CORPUS and len(covering(subject)) > GENERIC_SHARE * total:
            return False
        return not (len(topics) >= MIN_CORPUS and in_topics[subject] > CONTEXT_SHARE * len(topics))

    for topic in topics:
        topic.specific = [s for s in topic.subjects if specific(s)]
        if topic.specific:
            topic.label = ", ".join(topic.specific[:3])
        else:
            topic.supply = []
            continue
        needed = max(1, math.ceil(len(topic.specific) / 2))
        hits: Counter[int] = Counter(i for s in topic.specific for i in covering(s))
        ranked = [
            (count, scores[i], model.ids[i])
            for i, count in hits.items()
            if count >= needed and scores[i] >= SUPPLY_MIN_SCORE
        ]
        topic.supply = [r for _, _, r in sorted(ranked, key=lambda c: (-c[0], -c[1], c[2]))]


def gaps(topics: list[Topic]) -> list[Topic]:
    return [t for t in topics if t.demand >= GAP_MIN_DEMAND and t.specific and not t.supply]
