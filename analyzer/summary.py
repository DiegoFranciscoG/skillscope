"""Own summaries built from measured facts, never from third-party sentences.

"Qué hace" (2–3 sentences) and "Cuándo usarla" are composed with templates from the type,
category, cause, counts, declared tools, license, activity and single keywords. The copy
guard then rejects anything that shares 16+ consecutive words with the original text.
"""

from __future__ import annotations

from datetime import datetime

from analyzer.copyguard import overlaps
from analyzer.model import Artifact
from analyzer.text import fold, is_generic, stem, words
from analyzer.validate import WHEN_RE
from pipeline.clock import days_between, parse_iso

MAX_SUMMARY = 320

TYPE_PHRASE = {
    "skill": "Skill",
    "plugin": "Plugin",
    "marketplace": "Marketplace",
    "mcp_server": "Servidor MCP",
    "agent": "Agente",
    "command": "Comando",
    "hook": "Hook",
    "awesome_list": "Lista curada",
    "template": "Plantilla",
}
CATEGORY_PHRASE = {
    "development": "de desarrollo de software",
    "testing": "de pruebas",
    "code_review": "de revisión de código",
    "devops": "de DevOps y CI/CD",
    "security": "de seguridad",
    "data": "de datos y BI",
    "ai_ml": "de IA y machine learning",
    "docs_writing": "de documentación y escritura",
    "design_ux": "de diseño y UX",
    "productivity": "de productividad y oficina",
    "finance_legal": "de finanzas y legal",
    "research": "de investigación",
    "education": "de educación",
    "integrations": "de integraciones",
}
CAUSE_PHRASE = {
    "automate": "automatizar tareas repetitivas",
    "standardize": "estandarizar un estilo de trabajo",
    "comply": "cumplir normas y políticas",
    "onboard": "acelerar el aprendizaje de gente nueva",
    "integrate": "conectar el agente con herramientas externas",
    "reduce_errors": "reducir errores",
    "generate_docs": "generar documentos",
}
CATEGORY_WHEN = {
    "development": "Al escribir, depurar o reorganizar código.",
    "testing": "Cuando faltan pruebas o la CI falla de forma intermitente.",
    "code_review": "Antes de fusionar un pull request o al pedir una revisión.",
    "devops": "Al preparar despliegues, pipelines o infraestructura.",
    "security": "Antes de publicar código o al auditar un proyecto.",
    "data": "Al analizar datos, escribir consultas o armar reportes.",
    "ai_ml": "Al construir o evaluar funciones con modelos de lenguaje.",
    "docs_writing": "Cuando hay que escribir o corregir documentación.",
    "design_ux": "Al revisar interfaces, accesibilidad o estilos visuales.",
    "productivity": "Para ordenar correo, notas, reuniones o documentos de oficina.",
    "finance_legal": "Al revisar facturas, impuestos o contratos.",
    "research": "Al leer, resumir o comparar trabajos de investigación.",
    "education": "Para estudiar, practicar o enseñar un tema.",
    "integrations": "Para conectar el agente con un servicio externo.",
}
LICENSE_FREE = {None, "NOASSERTION"}


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " y " + items[-1]


def counts_phrase(repo_type: str, counts: dict[str, int], links: int) -> str:
    if repo_type == "awesome_list":
        return f" con {_plural(links, 'enlace', 'enlaces')} a repositorios"
    if repo_type == "marketplace":
        plugins = counts.get("plugins", 0)
        parts = [_plural(plugins, "plugin", "plugins")] if plugins else []
    else:
        parts = []
    for key, one, many in (
        ("skills", "skill", "skills"),
        ("commands", "comando", "comandos"),
        ("agents", "agente", "agentes"),
        ("hooks", "hook", "hooks"),
    ):
        if counts.get(key):
            parts.append(_plural(counts[key], one, many))
    if not parts:
        return ""
    verb = " que agrupa " if repo_type == "marketplace" else " con "
    return verb + _join(parts)


def activity_phrase(meta_last_commit: str | None, archived: bool, now: datetime) -> str:
    if archived:
        return "archivado por su autor"
    days = days_between(parse_iso(meta_last_commit), now)
    if days is None:
        return ""
    whole = int(days)
    if whole == 0:
        return "último commit hoy"
    return f"último commit hace {_plural(whole, 'día', 'días')}"


def build_lead(
    *,
    repo_type: str,
    category: str,
    cause: str,
    counts: dict[str, int],
    links: int,
    keywords: list[str],
) -> str:
    """First two sentences: what it is and what it is for (static per commit)."""
    first = f"{TYPE_PHRASE[repo_type]} {CATEGORY_PHRASE[category]}"
    first += counts_phrase(repo_type, counts, links) + "."
    kw = ", ".join(keywords[:4])
    second = f"Sirve para {CAUSE_PHRASE[cause]}" + (f": {kw}." if kw else ".")
    return f"{first} {second}"


def static_facts(tools: list[str], license_id: str | None) -> list[str]:
    facts: list[str] = []
    if tools:
        short = sorted({t.split("(")[0] for t in tools})[:4]
        facts.append(f"declara las herramientas {_join(short)}")
    if license_id in LICENSE_FREE:
        facts.append("sin licencia estándar" if license_id else "sin licencia")
    else:
        facts.append(f"licencia {license_id}")
    return facts


def compose_summary(lead: str, facts: list[str], activity: str) -> str:
    """Lead + facts + activity, dropping facts first if the text exceeds 320 characters."""
    parts = [*facts, activity] if activity else list(facts)
    while True:
        if not parts:
            return lead[:MAX_SUMMARY]
        third = "; ".join(parts)
        candidate = f"{lead} {third[0].upper()}{third[1:]}."
        if len(candidate) <= MAX_SUMMARY:
            return candidate
        parts.pop(0)


def build_summary(
    *,
    repo_type: str,
    category: str,
    cause: str,
    counts: dict[str, int],
    links: int,
    keywords: list[str],
    tools: list[str],
    license_id: str | None,
    last_commit: str | None,
    archived: bool,
    now: datetime,
) -> str:
    lead = build_lead(
        repo_type=repo_type,
        category=category,
        cause=cause,
        counts=counts,
        links=links,
        keywords=keywords,
    )
    return compose_summary(
        lead, static_facts(tools, license_id), activity_phrase(last_commit, archived, now)
    )


def trigger_words(description: str, limit: int = 4) -> list[str]:
    """Content words after a "use when …" clause, as single keywords (not a quote)."""
    folded = fold(description)
    match = WHEN_RE.search(folded)
    clause = folded[match.end() :] if match else ""
    out: list[str] = []
    seen: set[str] = set()
    for word in words(clause):
        if is_generic(word) or stem(word) in seen:
            continue
        seen.add(stem(word))
        out.append(word)
        if len(out) >= limit:
            break
    return out


def build_when(category: str, artifacts: list[Artifact]) -> list[str]:
    items: list[str] = []
    for artifact in artifacts:
        if artifact.kind not in {"skill", "agent"} or not artifact.description:
            continue
        if not artifact.has_when:
            continue
        triggers = trigger_words(artifact.description)
        if triggers:
            items.append(f"«{artifact.name}» se activa con: {_join(triggers)}.")
        if len(items) >= 4:
            break
    items.append(CATEGORY_WHEN[category])
    if not any(a.has_when for a in artifacts):
        items.append("Ninguna descripción dice cuándo usarla: revisa el README antes de instalar.")
    return items


def guarded(text: str, source: str, fallback: str) -> str:
    """Use ``fallback`` if ``text`` would copy 16+ consecutive words from ``source``."""
    return fallback if overlaps(text, source) else text
