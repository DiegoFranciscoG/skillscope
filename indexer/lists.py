"""Derived lists, each with its own documented criterion (docs/algoritmo.md §2)."""

from __future__ import annotations

from dataclasses import dataclass

LIST_SIZE = 50
SAFE_MIN_SCORE = 40
NEEDED_MIN_SCORE = 50
NO_ARTIFACT_TYPES = frozenset({"awesome_list", "template"})
NEW_DAYS = 30


@dataclass(slots=True)
class Ranked:
    id: str
    type: str
    category: str
    total: int
    quality: float
    adoption: float
    social: float
    utility: float
    penalty: int
    stars: int
    mentions_30d: float
    trend: float
    created_days: float | None = None  # age of the repository on GitHub


def _ids(items: list[Ranked]) -> list[str]:
    return [i.id for i in items[:LIST_SIZE]]


def most_used(items: list[Ranked]) -> list[str]:
    return _ids(sorted(items, key=lambda i: (-i.adoption, -i.stars, i.id)))


def most_mentioned(items: list[Ranked]) -> list[str]:
    mentioned = [i for i in items if i.mentions_30d > 0]
    return _ids(sorted(mentioned, key=lambda i: (-i.mentions_30d, -i.social, i.id)))


def newest(items: list[Ranked]) -> list[str]:
    """Created on GitHub in the last 30 days, best score first: what to try this month."""
    recent = [i for i in items if i.created_days is not None and i.created_days <= NEW_DAYS]
    return _ids(sorted(recent, key=lambda i: (-i.total, -i.stars, i.id)))


def trending(items: list[Ranked]) -> list[str]:
    rising = [i for i in items if i.trend > 0]
    return _ids(sorted(rising, key=lambda i: (-i.trend, -i.total, i.id)))


def most_useful(items: list[Ranked]) -> list[str]:
    return _ids(sorted(items, key=lambda i: (-(i.utility + i.quality - i.penalty), -i.total, i.id)))


def safest(items: list[Ranked]) -> list[str]:
    eligible = [i for i in items if i.type not in NO_ARTIFACT_TYPES and i.total >= SAFE_MIN_SCORE]
    return _ids(sorted(eligible, key=lambda i: (i.penalty, -i.total, i.id)))


def riskiest(items: list[Ranked]) -> list[str]:
    risky = [i for i in items if i.penalty > 0]
    return _ids(sorted(risky, key=lambda i: (-i.penalty, -i.stars, i.id)))


def most_needed(items: list[Ranked], demand: dict[str, float]) -> list[dict[str, object]]:
    """Per category: demand / (1 + supply), supply = repos of the category with score ≥ 50."""
    supply: dict[str, int] = {}
    for item in items:
        if item.total >= NEEDED_MIN_SCORE:
            supply[item.category] = supply.get(item.category, 0) + 1
    rows = [
        {
            "category": category,
            "demand": round(value, 2),
            "supply": supply.get(category, 0),
            "ratio": round(value / (1 + supply.get(category, 0)), 3),
        }
        for category, value in demand.items()
        if value > 0
    ]
    return sorted(rows, key=lambda r: (-float(str(r["ratio"])), -float(str(r["demand"]))))


def all_lists(items: list[Ranked], demand: dict[str, float]) -> dict[str, object]:
    return {
        "newest": newest(items),
        "most_used": most_used(items),
        "most_mentioned": most_mentioned(items),
        "trending": trending(items),
        "most_useful": most_useful(items),
        "safest": safest(items),
        "riskiest": riskiest(items),
        "most_needed": most_needed(items, demand),
    }
