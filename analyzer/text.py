"""Text normalization shared by classification, search and embeddings.

The browser runs the same algorithm (``web/src/search/tokenize.ts``); the shared cases in
``data/samples/tokenize-cases.json`` are checked by pytest and by Vitest, so both sides always
produce identical tokens (docs/algoritmo.md §3.1).
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# Multi-word phrases and symbols rewritten before splitting (applied in this order).
PHRASES: tuple[tuple[str, str], ...] = (
    (r"c\+\+", " cpp "),
    (r"c#", " csharp "),
    (r"f#", " fsharp "),
    (r"\.net\b", " dotnet "),
    (r"node\.js", " nodejs "),
    (r"pull[\s_-]+requests?", " pr "),
    (r"merge[\s_-]+requests?", " pr "),
    (r"code[\s_-]+reviews?", " review "),
    (r"bases?\s+de\s+datos", " database "),
    (r"hojas?\s+de\s+calculo", " spreadsheet "),
    (r"inteligencia\s+artificial", " ai "),
    (r"aprendizaje\s+automatico", " ml "),
    (r"machine[\s_-]+learning", " ml "),
    (r"control\s+de\s+versiones", " git "),
    (r"linea\s+de\s+comandos", " cli "),
    (r"command[\s_-]+line", " cli "),
    (r"end[\s_-]+to[\s_-]+end", " e2e "),
    (r"de\s+extremo\s+a\s+extremo", " e2e "),
    (r"integracion\s+continua", " ci "),
    (r"flujos?\s+de\s+trabajo", " workflow "),
    (r"power[\s_-]+bi", " powerbi "),
)
_PHRASES = tuple((re.compile(p), r) for p, r in PHRASES)
_WORD = re.compile(r"[a-z0-9]+")

STOPWORDS: frozenset[str] = frozenset(
    """
    a an the and or of to in on for with by from at as is are be been being was were this that
    these those it its into your you we our my me i use used uses using when how what which who
    whom can could will would should shall may might must need needs want wants any all some more
    most other than then there their them they not no yes if so do does did done get gets got
    help helps make makes like just also via about after before over under up down out only each
    every both such very one two three new way thing things etc eg ie per vs let lets please
    always never here where why while within without whether
    el la los las un una unos unas de del al en y o u e que con por para sin sobre entre como mas
    pero su sus se es son ser esta este estos estas eso esa ese lo le les mi mis tu tus yo me nos
    necesito necesita necesitamos quiero quisiera busco buscar hay algo alguna algun alguno cual
    cuando donde muy tambien ya hacer hace puede pueda poder todo todos toda todas mismo cada otro
    otra otros otras desde hasta segun durante ante tras porque pues si no asi usa usar uso
    """.split()
)

# Spanish words and English variants mapped to one canonical English term.
# fmt: off
LEXICON: dict[str, str] = {
    # review and code
    "revisar": "review", "revision": "review", "revisiones": "review", "revisa": "review",
    "reviewing": "review", "reviewer": "review", "reviewers": "review", "prs": "pr",
    "codigo": "code", "refactorizar": "refactor", "refactorizacion": "refactor",
    "depurar": "debug", "depuracion": "debug", "corregir": "fix", "fallo": "failure",
    "fallos": "failure", "rendimiento": "performance", "lento": "slow", "lenta": "slow",
    "rapido": "fast", "rama": "branch", "ramas": "branch", "fusionar": "merge",
    "repo": "repository", "repos": "repository", "repositorio": "repository",
    "repositorios": "repository",
    # testing
    "prueba": "test", "pruebas": "test", "testear": "test", "testeo": "test",
    "unitaria": "unit", "unitarias": "unit", "unitario": "unit", "unitarios": "unit",
    "unittest": "test",
    # security
    "seguridad": "security", "secreto": "secret", "secretos": "secret",
    "contrasena": "password", "contrasenas": "password", "clave": "key", "claves": "key",
    "vulnerabilidad": "vulnerability", "vulnerabilidades": "vulnerability",
    "auditoria": "audit", "auditar": "audit",
    # docs and writing
    "documentacion": "docs", "documentation": "docs", "documentar": "docs",
    "documento": "document", "documentos": "document", "escribir": "write",
    "escribas": "write", "escribe": "write",
    "escritura": "write", "redactar": "write", "redaccion": "write", "estilo": "style",
    "traducir": "translate", "traduccion": "translate", "idioma": "language",
    "idiomas": "language", "resumir": "summarize", "resumen": "summary",
    "articulo": "article", "articulos": "article", "plantilla": "template",
    "plantillas": "template", "i18n": "translate",
    # data
    "datos": "data", "consulta": "query", "consultas": "query", "tabla": "table",
    "tablas": "table", "grafico": "chart", "graficos": "chart", "tablero": "dashboard",
    "informe": "report", "informes": "report", "reporte": "report", "reportes": "report",
    "analizar": "analysis", "analisis": "analysis",
    # design
    "diseno": "design", "disenos": "design", "interfaz": "ui", "interfaces": "ui",
    "accesibilidad": "accessibility", "accesible": "accessibility",
    "accessible": "accessibility", "a11y": "accessibility", "usabilidad": "usability",
    # devops
    "despliegue": "deploy", "desplegar": "deploy", "deployment": "deploy",
    "contenedor": "container", "contenedores": "container", "nube": "cloud",
    "infraestructura": "infrastructure", "k8s": "kubernetes",
    # finance and legal
    "factura": "invoice", "facturas": "invoice", "facturacion": "invoice",
    "impuesto": "tax", "impuestos": "tax", "tributario": "tax", "contabilidad": "accounting",
    "contable": "accounting", "finanzas": "finance", "financiero": "finance",
    "contrato": "contract", "contratos": "contract", "juridico": "legal",
    "cumplimiento": "compliance", "normativa": "compliance", "norma": "compliance",
    "normas": "compliance", "nomina": "payroll",
    # research and education
    "investigacion": "research", "investigar": "research", "cientifico": "science",
    "educacion": "education", "estudiante": "student", "estudiantes": "student",
    "alumno": "student", "alumnos": "student", "ensenar": "teach", "examen": "exam",
    "examenes": "exam", "aprender": "learn", "aprendizaje": "learn", "curso": "course",
    "cursos": "course", "tarjetas": "flashcard",
    # productivity and integrations
    "tarea": "task", "tareas": "task", "correo": "email", "correos": "email",
    "e-mail": "email", "reunion": "meeting", "reuniones": "meeting",
    "calendario": "calendar", "notas": "note", "productividad": "productivity",
    "automatizar": "automate", "automatizacion": "automate", "automation": "automate",
    "integrar": "integration", "integracion": "integration", "integrations": "integration",
    "conectar": "connect", "conector": "connect", "migrar": "migration",
    "migracion": "migration", "herramienta": "tool", "herramientas": "tool",
    "comando": "command", "comandos": "command", "agente": "agent", "agentes": "agent",
    "complemento": "plugin", "complementos": "plugin", "habilidad": "skill",
    "habilidades": "skill", "generar": "generate", "crear": "create", "mejorar": "improve",
    "explicar": "explain", "apis": "api", "js": "javascript", "ts": "typescript", "py": "python",
}
# fmt: on

# Words too generic to describe a repository (kept for search, dropped from keywords).
GENERIC: frozenset[str] = frozenset(
    """
    skill plugin agent claude code tool user file repository project task work run ask step
    answer md readme example generate create write read add list check find show set time good
    best first last next type name description mcp main github com http https www json yaml
    share paste open start mention say give has have got look see try want help need anything
    everything something thing way lot really other others available simple quick easy
    recently changed change below above missing drop follow describe step steps across
    """.split()
)

PROTECTED: frozenset[str] = frozenset(
    {"pr", "ci", "cd", "ai", "ml", "ui", "ux", "e2e", "sql", "api"}
)


def fold(text: str) -> str:
    """NFKD, drop accents, lower case."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def normalize(text: str) -> str:
    folded = fold(text)
    for pattern, replacement in _PHRASES:
        folded = pattern.sub(replacement, folded)
    return folded


def words(text: str) -> list[str]:
    """Readable canonical words (no stemming): used for keywords and summaries."""
    out: list[str] = []
    for raw in _WORD.findall(normalize(text)):
        if len(raw) < 2 or raw.isdigit() or raw in STOPWORDS:
            continue
        out.append(LEXICON.get(raw, raw))
    return out


@lru_cache(maxsize=65536)
def stem(word: str) -> str:
    """Light suffix stripper, identical to the TypeScript version."""
    if word in PROTECTED or len(word) <= 3:
        return word
    w = word
    if w.endswith("ies") and len(w) > 4:
        w = w[:-3] + "y"
    elif w.endswith("sses"):
        w = w[:-2]
    elif w.endswith("s") and not w.endswith(("ss", "us", "is")) and len(w) > 3:
        w = w[:-1]
    if w.endswith("ing") and len(w) > 5:
        w = w[:-3]
        if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "lsz":
            w = w[:-1]
    elif w.endswith("ed") and len(w) > 4:
        w = w[:-2]
        if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "lsz":
            w = w[:-1]
    if w.endswith("e") and len(w) > 3:
        w = w[:-1]
    return w


def tokens(text: str) -> list[str]:
    """Search tokens: canonical words, stemmed."""
    return [stem(w) for w in words(text)]


@lru_cache(maxsize=1)
def _generic_stems() -> frozenset[str]:
    return frozenset(stem(w) for w in GENERIC)


def is_generic(word: str) -> bool:
    return word not in PROTECTED and (len(word) <= 2 or stem(word) in _generic_stems())


def keywords(text: str) -> list[str]:
    """Readable descriptive words (generic ones removed), in order of appearance."""
    return [w for w in words(text) if not is_generic(w)]
