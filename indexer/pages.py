"""One static HTML page per repository (schema.org SoftwareSourceCode), sitemap and robots.

Search engines index these pages; the interactive app stays a single page. All third-party
text goes through ``html.escape`` and the JSON-LD block escapes ``<`` so it can never close
the script element (docs/investigacion.md #56, #57).
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from analyzer.lexicon import CATEGORY_LABELS, TYPE_LABELS
from indexer.index import Entry, SiteData
from pipeline.jsonio import write_text

PAGE_CSP = (
    "default-src 'none'; style-src 'self'; img-src 'self' data:; base-uri 'none'; "
    "form-action 'none'; require-trusted-types-for 'script'"
)
RISK_TEXT = ("sin banderas de riesgo", "riesgo bajo", "riesgo medio", "riesgo alto")


def _decimal(value: float) -> str:
    """One decimal with a Spanish comma: 16.77 -> "16,8"."""
    return f"{value:.1f}".replace(".", ",").removesuffix(",0")


def _json_ld(data: dict[str, Any]) -> str:
    return (
        json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _structured(entry: Entry, data: SiteData, url: str, now: datetime) -> dict[str, Any]:
    a = entry.analysis
    meta = a.meta
    doc: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "SoftwareSourceCode",
        "name": meta.name,
        "description": a.summary(now),
        "url": url,
        "keywords": ", ".join(a.keywords[:10]),
        "author": {"@type": "Person" if meta.owner else "Organization", "name": meta.owner},
        "isPartOf": {"@type": "WebSite", "name": "Skillscope", "url": data.site_url},
    }
    if not a.sample:
        doc["codeRepository"] = meta.url
    if meta.license and meta.license not in {"NOASSERTION", "OTHER"}:
        doc["license"] = f"https://spdx.org/licenses/{meta.license}.html"
    if meta.pushed_at:
        doc["dateModified"] = meta.pushed_at
    return doc


def page(entry: Entry, data: SiteData, now: datetime) -> str:
    a = entry.analysis
    meta = a.meta
    url = f"{data.site_url}s/{meta.owner}/{meta.name}/"
    app = f"../../../?r={escape(meta.owner)}%2F{escape(meta.name)}"
    title = f"{meta.owner}/{meta.name}"
    install = a.install.one_liner or (a.install.note or "Sigue las instrucciones del README.")
    risks = (
        "".join(f"<li>{escape(f.title)} (−{f.penalty})</li>" for f in a.risks)
        or "<li>No se detectaron banderas de riesgo en los archivos analizados.</li>"
    )
    when = "".join(f"<li>{escape(w)}</li>" for w in a.when)
    repo_link = (
        '<p class="muted">Repositorio ficticio de ejemplo.</p>'
        if a.sample
        else f'<p><a href="{escape(meta.url)}" rel="noopener noreferrer">Ver en GitHub</a></p>'
    )
    components = "".join(
        f"<li>{escape(c.label)}: {_decimal(c.points)} de {c.max:g}</li>"
        for c in entry.score.components
    )
    description = escape(a.summary(now))
    level = (a.risk_penalty > 0) + (a.risk_penalty >= 6) + (a.risk_penalty >= 13)
    tags = " · ".join(
        (
            escape(TYPE_LABELS.get(a.type, a.type)),
            escape(CATEGORY_LABELS.get(a.category, a.category)),
            f"puntaje {entry.score.total} de 100",
            RISK_TEXT[min(3, level)],
        )
    )
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{PAGE_CSP}">
<title>{escape(title)} · Skillscope</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{escape(url)}">
<link rel="stylesheet" href="../../../page.css">
<link rel="icon" href="../../../favicon.svg" type="image/svg+xml">
<script type="application/ld+json">{_json_ld(_structured(entry, data, url, now))}</script>
</head>
<body>
<main>
<p><a href="../../../">Skillscope</a></p>
<h1>{escape(title)}</h1>
<p class="tags">{tags}</p>
<h2>Qué hace</h2>
<p>{escape(a.what(now))}</p>
{repo_link}
<h2>Cuándo usarla</h2>
<ul>{when}</ul>
<h2>Cómo se instala</h2>
<pre><code>{escape(install)}</code></pre>
<h2>Qué riesgos tiene</h2>
<ul>{risks}</ul>
<h2>Puntaje</h2>
<ul>{components}</ul>
<p><a href="{app}">Abrir en el buscador de Skillscope</a></p>
</main>
</body>
</html>
"""


SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def safe_path(owner: str, name: str) -> bool:
    """Owner and repository names become folders: only GitHub's own character set passes."""
    return all(SAFE_SEGMENT.match(part) and ".." not in part for part in (owner, name))


def write(data: SiteData, out_dir: Path, now: datetime) -> int:
    # Start clean: a repository that left the index (opt-out, deleted) must lose its page too.
    shutil.rmtree(out_dir / "s", ignore_errors=True)
    count = 0
    for entry in data.entries:
        meta = entry.analysis.meta
        if not safe_path(meta.owner, meta.name):
            continue
        write_text(out_dir / "s" / meta.owner / meta.name / "index.html", page(entry, data, now))
        count += 1
    urls = [
        f"  <url><loc>{escape(data.site_url)}</loc><lastmod>{data.built_at[:10]}</lastmod></url>"
    ]
    for entry in data.entries[:49_999]:
        meta = entry.analysis.meta
        lastmod = (meta.pushed_at or data.built_at)[:10]
        loc = escape(f"{data.site_url}s/{meta.owner}/{meta.name}/")
        urls.append(f"  <url><loc>{loc}</loc><lastmod>{lastmod}</lastmod></url>")
    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>\n"
    )
    write_text(out_dir / "sitemap.xml", sitemap)
    write_text(
        out_dir / "robots.txt",
        f"User-agent: *\nAllow: /\nSitemap: {data.site_url}sitemap.xml\n",
    )
    return count
