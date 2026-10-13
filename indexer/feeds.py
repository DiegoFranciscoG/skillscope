"""Weekly bulletin as RSS 2.0 and JSON Feed 1.1 (docs/investigacion.md #54, #55).

Items: repositories that entered the index in the last 7 days, plus one digest with the
fastest risers and the ecosystem gaps. Every id is stable so readers never see duplicates.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from indexer.index import Entry, SiteData
from pipeline.clock import iso, parse_iso
from pipeline.jsonio import write_json, write_text

NEW_DAYS = 7
MAX_NEW = 50
TITLE = "Skillscope"
DESCRIPTION = (
    "Skills y plugins para agentes de código: nuevos, en tendencia y huecos del ecosistema."
)


def _page(data: SiteData, entry: Entry) -> str:
    return f"{data.site_url}s/{entry.analysis.meta.owner}/{entry.analysis.meta.name}/"


def _items(data: SiteData, now: datetime) -> list[dict[str, Any]]:
    cutoff = now - timedelta(days=NEW_DAYS)
    by_id = {e.id: e for e in data.entries}
    fresh = [
        e
        for e in data.entries
        if (parse_iso(e.first_seen) or now) >= cutoff and not e.analysis.sample
    ]
    fresh.sort(key=lambda e: (e.first_seen, e.score.total), reverse=True)
    items: list[dict[str, Any]] = []
    for entry in fresh[:MAX_NEW]:
        items.append(
            {
                "id": f"repo:{entry.id.lower()}",
                "url": _page(data, entry),
                "title": f"Nuevo: {entry.id} (puntaje {entry.score.total})",
                "content_text": entry.analysis.summary(now),
                "date_published": entry.first_seen,
                "tags": [entry.analysis.type, entry.analysis.category],
            }
        )
    week = now.strftime("%G-W%V")
    risers = [by_id[i] for i in data.lists.get("trending", [])[:5] if i in by_id]
    gaps = [g.label for g in data.gaps[:5]]
    lines = [f"Repositorios indexados: {len(data.entries)}. Nuevos esta semana: {len(fresh)}."]
    if risers:
        lines.append("Lo que más subió: " + ", ".join(e.id for e in risers) + ".")
    if gaps:
        lines.append("Huecos del ecosistema: " + "; ".join(gaps) + ".")
    items.insert(
        0,
        {
            "id": f"digest:{week}",
            "url": f"{data.site_url}?tab=trending",
            "title": f"Boletín Skillscope {week}",
            "content_text": " ".join(lines),
            "date_published": iso(now),
            "tags": ["boletín"],
        },
    )
    return items


def write(data: SiteData, out_dir: Path, now: datetime) -> None:
    items = _items(data, now)
    json_feed = {
        "version": "https://jsonfeed.org/version/1.1",
        "title": TITLE,
        "home_page_url": data.site_url,
        "feed_url": f"{data.site_url}feed.json",
        "description": DESCRIPTION,
        "language": "es",
        "items": items,
    }
    write_json(out_dir / "feed.json", json_feed, pretty=True)

    def rss_item(item: dict[str, Any]) -> str:
        published = parse_iso(item["date_published"]) or now
        return (
            "    <item>\n"
            f"      <title>{escape(item['title'])}</title>\n"
            f"      <link>{escape(item['url'])}</link>\n"
            f'      <guid isPermaLink="false">{escape(item["id"])}</guid>\n'
            f"      <pubDate>{format_datetime(published)}</pubDate>\n"
            f"      <description>{escape(item['content_text'])}</description>\n"
            "    </item>\n"
        )

    rss = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        f"    <title>{TITLE}</title>\n"
        f"    <link>{escape(data.site_url)}</link>\n"
        f"    <description>{escape(DESCRIPTION)}</description>\n"
        "    <language>es</language>\n"
        f"    <lastBuildDate>{format_datetime(now)}</lastBuildDate>\n"
        "    <ttl>60</ttl>\n"
        f'    <atom:link href="{escape(data.site_url)}feed.xml" rel="self" '
        'type="application/rss+xml"/>\n'
        + "".join(rss_item(i) for i in items)
        + "  </channel>\n</rss>\n"
    )
    write_text(out_dir / "feed.xml", rss)
