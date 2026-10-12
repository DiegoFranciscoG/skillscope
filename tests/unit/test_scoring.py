"""Numeric tests: each formula of docs/algoritmo.md §1 pinned to exact values."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from analyzer.model import Install, RepoAnalysis, RiskFlag
from analyzer.scoring import (
    SignalInput,
    adoption,
    maintenance,
    mention_weight,
    quality,
    risk,
    risk_level,
    score,
    social,
    utility,
)
from pipeline.clock import iso
from pipeline.models import RepoMeta

NOW = datetime(2026, 10, 12, tzinfo=UTC)


def make(
    facts: dict[str, Any] | None = None, risks: list[int] | None = None, **meta: Any
) -> RepoAnalysis:
    base_meta = {"id": "o/r", "owner": "o", "name": "r", "url": "u", "license": "MIT"}
    base_meta.update(meta)
    return RepoAnalysis(
        meta=RepoMeta(**base_meta),
        sample=False,
        type="skill",
        category="development",
        categories=[],
        cause="automate",
        category_terms=[],
        artifacts=[],
        counts={},
        tools=[],
        readme_lang="en",
        keywords=[],
        marketplace_name=None,
        marketplace_entries=[],
        list_links=[],
        install=Install("manual"),
        risks=[RiskFlag(f"r{i}", "high", p, "t", "w") for i, p in enumerate(risks or [])],
        facts=facts or {},
        index_text="",
        summary_lead="",
        summary_facts=[],
        included=[],
    )


FULL_QUALITY = {
    "analyzable": 3,
    "valid": 3,
    "described": 3,
    "with_when": 3,
    "skills_measured": 3,
    "skills_short": 3,
    "support_files": True,
    "examples": True,
    "readme": True,
    "readme_install": True,
    "tests_or_ci": True,
}


def test_quality_maximum_is_25() -> None:
    component = quality(make(FULL_QUALITY))
    assert component.points == 25
    assert [f.points for f in component.factors] == [6, 5, 4, 3, 3, 2, 2]


def test_quality_partial_values() -> None:
    facts = {
        "analyzable": 2,
        "valid": 1,
        "described": 2,
        "with_when": 1,
        "skills_measured": 2,
        "skills_short": 1,
        "readme": True,
    }
    component = quality(make(facts, license="NOASSERTION"))
    # 3 + 2.5 + 1.5 + 0 + 1 + 1 + 0
    assert component.points == 9.0


def test_quality_without_skills_or_license() -> None:
    component = quality(make({"any_description": True}, license=None))
    # q1 0, q2 2.5 (description only), q3 2 (neutral), q6 0
    assert component.points == 4.5


def test_maintenance_values() -> None:
    analysis = make(
        last_commit_at=iso(NOW - timedelta(days=90)),
        latest_release_at=iso(NOW - timedelta(days=200)),
        open_issues=0,
        closed_issues=8,
        ci_state="SUCCESS",
    )
    component = maintenance(analysis, NOW)
    assert [f.points for f in component.factors] == [5.0, 1.5, 3.6, 3.0]
    assert component.points == 13.1


def test_maintenance_archived_and_pending_ci() -> None:
    analysis = make(
        archived=True,
        last_commit_at=iso(NOW),
        latest_release_at=iso(NOW),
        ci_state="PENDING",
    )
    component = maintenance(analysis, NOW)
    # recency 0, release 0, issues (0+1)/(0+2)·4 = 2, CI pending 1.5
    assert component.points == 3.5


def test_adoption_with_and_without_package() -> None:
    signals = SignalInput(collections=8)
    with_npm = make(stars=10_000, forks=1_000)
    with_npm.npm_downloads = 10_000
    assert adoption(with_npm, signals).points == 20
    without_npm = make(stars=10_000, forks=1_000)
    assert adoption(without_npm, signals).points == 20  # rescaled 18 → 20
    small = adoption(make(stars=99, forks=0), SignalInput())
    assert small.factors[0].points == 5.0  # log10(100) / log10(10001) ≈ 0.5
    assert small.points == pytest.approx(5.56, abs=0.01)


@pytest.mark.parametrize(
    ("source", "age", "engagement", "expected"),
    [
        ("hackernews", 0, 0, 1.0),
        ("hackernews", 30, 0, 0.5),
        ("hackernews", 0, 999, 2.0),
        ("reddit", 0, 0, 0.8),
        ("mastodon", 60, 0, 0.125),
        ("hackernews", 181, 1000, 0.0),
    ],
)
def test_mention_weight(source: str, age: int, engagement: int, expected: float) -> None:
    assert mention_weight(source, age, engagement) == pytest.approx(expected)


def test_social_scale() -> None:
    assert social(SignalInput(mention_weight=20)).points == 15
    assert social(SignalInput(mention_weight=0)).points == 0
    assert social(SignalInput(mention_weight=1)).points == pytest.approx(3.42, abs=0.01)


def test_utility_neutral_and_measured() -> None:
    assert utility(SignalInput()).points == 10
    measured = utility(
        SignalInput(matched_demand=10, category_demand=5, max_category_demand=10, has_demand=True)
    )
    assert measured.points == 16


def test_risk_penalty_is_capped() -> None:
    assert risk(make(risks=[10, 8, 8, 6])).points == -25
    assert risk(make(risks=[4])).points == -4
    assert [risk_level(p) for p in (0, 1, 5, 6, 12, 13, 25)] == [0, 1, 1, 2, 2, 3, 3]


def test_total_is_clamped_and_rounded() -> None:
    worst = make({}, risks=[10, 10, 10], license=None)
    result = score(worst, SignalInput(), NOW)
    assert result.total == 0
    best = make(
        FULL_QUALITY,
        stars=10_000,
        forks=1_000,
        last_commit_at=iso(NOW),
        latest_release_at=iso(NOW),
        closed_issues=1_000,
        ci_state="SUCCESS",
    )
    signals = SignalInput(
        collections=8,
        mention_weight=20,
        matched_demand=10,
        category_demand=1,
        max_category_demand=1,
        has_demand=True,
    )
    result = score(best, signals, NOW)
    assert result.total == 100
    assert result.get("quality") == 25
    assert result.to_dict()["components"][0]["id"] == "quality"
