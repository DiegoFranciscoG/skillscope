"""Transparent 0–100 score (docs/algoritmo.md §1).

Every constant lives here and every factor is reported with its measured value, so each
listing can show exactly why a repository got its score.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from analyzer.model import RepoAnalysis
from pipeline.clock import days_between, parse_iso

# Calidad -------------------------------------------------------------------------------------
Q_VALID, Q_WHEN, Q_SHORT, Q_EXAMPLES, Q_README, Q_LICENSE, Q_TESTS = 6, 5, 4, 3, 3, 2, 2
SKILL_MAX_LINES = 500
# Mantenimiento -------------------------------------------------------------------------------
M_RECENCY, M_RELEASE, M_ISSUES, M_CI = 10, 3, 4, 3
RECENCY_HALF_LIFE_DAYS = 90
# Adopción ------------------------------------------------------------------------------------
A_STARS, A_FORKS, A_COLLECTIONS, A_DOWNLOADS = 10, 3, 5, 2
STARS_REF, FORKS_REF, COLLECTIONS_REF, DOWNLOADS_REF = 10_000, 1_000, 8, 10_000
# Interés social ------------------------------------------------------------------------------
S_MAX = 15
MENTION_HALF_LIFE_DAYS = 30
MENTION_WINDOW_DAYS = 180
MENTION_REF = 20
SOURCE_WEIGHTS: dict[str, float] = {
    "hackernews": 1.0,
    "youtube": 0.9,
    "reddit": 0.8,
    "stackexchange": 0.7,
    "devto": 0.6,
    "mastodon": 0.5,
    "bluesky": 0.5,
    "lemmy": 0.5,
}
# Utilidad ------------------------------------------------------------------------------------
U_MATCHED, U_CATEGORY = 12, 8
U_NEUTRAL = 10
MATCH_REF = 10
# Riesgo --------------------------------------------------------------------------------------
R_MAX = 25

KNOWN_LICENSE_EXCEPTIONS = {"NOASSERTION", "OTHER"}


def sat(x: float) -> float:
    return max(0.0, min(1.0, x))


def log_ratio(value: float, reference: float, base: float = 10.0) -> float:
    return sat(math.log(1 + max(0.0, value), base) / math.log(1 + reference, base))


@dataclass(slots=True)
class Factor:
    id: str
    label: str
    value: str
    points: float
    max: float


@dataclass(slots=True)
class Component:
    id: str
    label: str
    points: float
    max: float
    factors: list[Factor] = field(default_factory=list)


@dataclass(slots=True)
class Score:
    total: int
    components: list[Component]

    def get(self, component_id: str) -> float:
        return next(c.points for c in self.components if c.id == component_id)

    def to_dict(self) -> dict[str, Any]:
        return {"total": self.total, "components": [asdict(c) for c in self.components]}


@dataclass(slots=True)
class SignalInput:
    collections: int = 0
    mention_weight: float = 0.0  # Σ w_i over the last 180 days (decayed)
    mentions_counted: int = 0
    matched_demand: float = 0.0  # Σ weight of demand questions this repo answers
    category_demand: float = 0.0
    max_category_demand: float = 0.0
    has_demand: bool = False


def _r(x: float) -> float:
    return round(x, 2)


def quality(analysis: RepoAnalysis) -> Component:
    f = analysis.facts
    analyzable = int(f.get("analyzable", 0))
    q1 = Q_VALID * (int(f.get("valid", 0)) / analyzable) if analyzable else 0.0
    described = int(f.get("described", 0))
    if described:
        q2 = Q_WHEN * int(f.get("with_when", 0)) / described
        q2_value = f"{f.get('with_when', 0)} de {described} descripciones"
    else:
        q2 = Q_WHEN / 2 if f.get("any_description") else 0.0
        q2_value = "sin skills ni agentes" + (" (hay descripción)" if q2 else "")
    measured = int(f.get("skills_measured", 0))
    if measured:
        q3 = (Q_SHORT - 1) * int(f.get("skills_short", 0)) / measured
        q3 += 1 if f.get("support_files") or f.get("all_very_short") else 0
        q3_value = f"{f.get('skills_short', 0)} de {measured} con ≤ {SKILL_MAX_LINES} líneas"
    else:
        q3, q3_value = Q_SHORT / 2, "sin SKILL.md"
    q4 = Q_EXAMPLES if f.get("examples") else 0.0
    q5 = Q_README if f.get("readme_install") else (1.0 if f.get("readme") else 0.0)
    license_id = analysis.meta.license
    if license_id is None:
        q6 = 0.0
    elif license_id in KNOWN_LICENSE_EXCEPTIONS:
        q6 = 1.0
    else:
        q6 = float(Q_LICENSE)
    q7 = Q_TESTS if f.get("tests_or_ci") else 0.0
    factors = [
        Factor("valid", "Formato válido", f"{f.get('valid', 0)} de {analyzable}", _r(q1), Q_VALID),
        Factor("when", "La descripción dice cuándo usarla", q2_value, _r(q2), Q_WHEN),
        Factor("short", "Archivo breve y detalle aparte", q3_value, _r(q3), Q_SHORT),
        Factor("examples", "Ejemplos", "sí" if q4 else "no", _r(q4), Q_EXAMPLES),
        Factor(
            "readme",
            "README con instalación",
            "sí" if q5 == Q_README else ("README sin instalación" if q5 else "sin README"),
            _r(q5),
            Q_README,
        ),
        Factor("license", "Licencia declarada", license_id or "ninguna", _r(q6), Q_LICENSE),
        Factor("tests", "Validador, pruebas o CI", "sí" if q7 else "no", _r(q7), Q_TESTS),
    ]
    total = q1 + q2 + q3 + q4 + q5 + q6 + q7
    return Component("quality", "Calidad del paquete", _r(total), 25, factors)


def maintenance(analysis: RepoAnalysis, now: datetime) -> Component:
    meta = analysis.meta
    days = days_between(parse_iso(meta.last_commit_at or meta.pushed_at), now)
    if meta.archived or days is None:
        m1 = 0.0
    else:
        m1 = M_RECENCY * math.pow(2.0, -days / RECENCY_HALF_LIFE_DAYS)
    release_days = days_between(parse_iso(meta.latest_release_at), now)
    if meta.archived or release_days is None:
        m2 = 0.0
    elif release_days <= 180:
        m2 = float(M_RELEASE)
    elif release_days <= 365:
        m2 = M_RELEASE / 2
    else:
        m2 = 0.0
    total_issues = meta.open_issues + meta.closed_issues
    m3 = M_ISSUES * (meta.closed_issues + 1) / (total_issues + 2)
    state = (meta.ci_state or "").upper()
    m4 = (
        float(M_CI)
        if state == "SUCCESS"
        else (M_CI / 2 if state in {"PENDING", "EXPECTED"} else 0.0)
    )
    factors = [
        Factor(
            "recency",
            "Recencia del último commit",
            "archivado" if meta.archived else (f"{int(days)} días" if days is not None else "—"),
            _r(m1),
            M_RECENCY,
        ),
        Factor(
            "release",
            "Releases recientes",
            f"{int(release_days)} días" if release_days is not None else "sin releases",
            _r(m2),
            M_RELEASE,
        ),
        Factor(
            "issues",
            "Issues cerrados",
            f"{meta.closed_issues} de {total_issues}",
            _r(m3),
            M_ISSUES,
        ),
        Factor("ci", "CI en verde", state.lower() or "sin CI", _r(m4), M_CI),
    ]
    return Component("maintenance", "Mantenimiento", _r(m1 + m2 + m3 + m4), 20, factors)


def adoption(analysis: RepoAnalysis, signals: SignalInput) -> Component:
    meta = analysis.meta
    a1 = A_STARS * log_ratio(meta.stars, STARS_REF)
    a2 = A_FORKS * log_ratio(meta.forks, FORKS_REF)
    a3 = A_COLLECTIONS * log_ratio(signals.collections, COLLECTIONS_REF, base=2.0)
    factors = [
        Factor("stars", "Estrellas (escala logarítmica)", str(meta.stars), _r(a1), A_STARS),
        Factor("forks", "Forks", str(meta.forks), _r(a2), A_FORKS),
        Factor(
            "collections",
            "Marketplaces y listas que lo incluyen",
            str(signals.collections),
            _r(a3),
            A_COLLECTIONS,
        ),
    ]
    if analysis.npm_downloads is not None:
        a4 = A_DOWNLOADS * log_ratio(analysis.npm_downloads, DOWNLOADS_REF)
        factors.append(
            Factor(
                "downloads",
                "Descargas npm del último mes",
                str(analysis.npm_downloads),
                _r(a4),
                A_DOWNLOADS,
            )
        )
        total = a1 + a2 + a3 + a4
    else:
        total = (a1 + a2 + a3) * 20 / 18
        factors.append(
            Factor(
                "downloads", "Descargas", "no publica paquete: el resto se reescala a 20", 0.0, 0.0
            )
        )
    return Component("adoption", "Adopción", _r(total), 20, factors)


def mention_weight(source: str, age_days: float, engagement: int) -> float:
    """Weight of one mention: source × recency decay × bounded engagement bonus."""
    if age_days > MENTION_WINDOW_DAYS:
        return 0.0
    decay = math.pow(2.0, -max(0.0, age_days) / MENTION_HALF_LIFE_DAYS)
    bonus = 1 + sat(math.log10(1 + max(0, engagement)) / 3)
    return SOURCE_WEIGHTS.get(source, 0.5) * decay * bonus


def social(signals: SignalInput) -> Component:
    points = S_MAX * log_ratio(signals.mention_weight, MENTION_REF, base=2.0)
    factors = [
        Factor(
            "mentions",
            "Menciones ponderadas (180 días)",
            f"{signals.mentions_counted} menciones, peso {signals.mention_weight:.2f}",
            _r(points),
            S_MAX,
        )
    ]
    return Component("social", "Interés social", _r(points), S_MAX, factors)


def utility(signals: SignalInput) -> Component:
    if not signals.has_demand:
        factors = [
            Factor("neutral", "Sin datos de demanda en este build", "neutral", U_NEUTRAL, 20)
        ]
        return Component("utility", "Utilidad declarada", U_NEUTRAL, 20, factors)
    u1 = U_MATCHED * log_ratio(signals.matched_demand, MATCH_REF, base=2.0)
    share = (
        signals.category_demand / signals.max_category_demand
        if signals.max_category_demand
        else 0.0
    )
    u2 = U_CATEGORY * share
    factors = [
        Factor(
            "matched",
            "Preguntas reales que responde",
            f"peso {signals.matched_demand:.1f}",
            _r(u1),
            U_MATCHED,
        ),
        Factor(
            "category",
            "Demanda de su categoría",
            f"{share:.0%} de la más pedida",
            _r(u2),
            U_CATEGORY,
        ),
    ]
    return Component("utility", "Utilidad declarada", _r(u1 + u2), 20, factors)


def risk(analysis: RepoAnalysis) -> Component:
    penalty = min(R_MAX, sum(f.penalty for f in analysis.risks))
    factors = [Factor(f.id, f.title, f.severity, -float(f.penalty), 0) for f in analysis.risks]
    return Component("risk", "Penalización por riesgo", -float(penalty), R_MAX, factors)


def score(analysis: RepoAnalysis, signals: SignalInput, now: datetime) -> Score:
    components = [
        quality(analysis),
        maintenance(analysis, now),
        adoption(analysis, signals),
        social(signals),
        utility(signals),
        risk(analysis),
    ]
    raw = sum(c.points for c in components)
    return Score(round(max(0.0, min(100.0, raw))), components)


def risk_level(penalty: int) -> int:
    if penalty <= 0:
        return 0
    if penalty <= 5:
        return 1
    if penalty <= 12:
        return 2
    return 3
