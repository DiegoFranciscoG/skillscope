"""SVG badge per indexed repository: "Skillscope | 87". Each badge in a README links back."""

from __future__ import annotations

import shutil
from html import escape
from pathlib import Path

from indexer.index import SiteData
from indexer.pages import safe_path
from pipeline.jsonio import write_text

CHAR_WIDTH = 6.6  # average width of an 11 px Verdana/DejaVu glyph


def _width(text: str) -> int:
    return int(len(text) * CHAR_WIDTH + 12)


def badge(score: int, label: str = "Skillscope") -> str:
    value = str(score)
    left, right = _width(label), _width(value)
    total = left + right
    title = escape(f"{label}: puntaje {value} de 100")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="20" role="img" '
        f'aria-label="{title}"><title>{title}</title>'
        f'<rect width="{left}" height="20" fill="#3f3f46"/>'
        f'<rect x="{left}" width="{right}" height="20" fill="#2b55c9"/>'
        '<g fill="#fff" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11">'
        f'<text x="{left / 2}" y="14" text-anchor="middle">{escape(label)}</text>'
        f'<text x="{left + right / 2}" y="14" text-anchor="middle">{escape(value)}</text>'
        "</g></svg>"
    )


def write(data: SiteData, out_dir: Path) -> int:
    shutil.rmtree(out_dir / "badge", ignore_errors=True)  # no badge outlives its repository
    count = 0
    for entry in data.entries:
        meta = entry.analysis.meta
        if not safe_path(meta.owner, meta.name):
            continue
        write_text(out_dir / "badge" / meta.owner / f"{meta.name}.svg", badge(entry.score.total))
        count += 1
    return count
