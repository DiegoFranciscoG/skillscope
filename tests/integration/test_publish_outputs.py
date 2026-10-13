"""Feeds, static pages, sitemap and badges produced by the offline build."""

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from indexer.badges import badge
from indexer.pages import _json_ld, safe_path
from tests.integration.test_build_offline import build


def test_feeds_sitemap_pages_and_badges(tmp_path: Path) -> None:
    result, data = build(tmp_path)
    site = data.parent

    rss = ET.parse(site / "feed.xml").getroot()
    channel = rss.find("channel")
    assert channel is not None
    assert channel.findtext("title") == "Skillscope"
    items = channel.findall("item")
    assert items and items[0].findtext("guid", "").startswith("digest:")

    feed = json.loads((site / "feed.json").read_text(encoding="utf-8"))
    assert feed["version"] == "https://jsonfeed.org/version/1.1"
    assert all(
        item["id"] and (item.get("content_text") or item.get("content_html"))
        for item in feed["items"]
    )

    urls = ET.parse(site / "sitemap.xml").getroot()
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    assert len(urls.findall("s:url", ns)) == result.published + 1
    assert "Sitemap: http://localhost:8080/sitemap.xml" in (site / "robots.txt").read_text()

    page = (site / "s" / "nimbus-labs" / "pr-review-kit" / "index.html").read_text(encoding="utf-8")
    assert "<h1>nimbus-labs/pr-review-kit</h1>" in page
    assert 'http-equiv="Content-Security-Policy"' in page
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
    assert match is not None
    structured = json.loads(match.group(1))
    assert structured["@type"] == "SoftwareSourceCode"
    assert "codeRepository" not in structured  # fictional sample repositories never link out
    for heading in ("Qué hace", "Cuándo usarla", "Cómo se instala", "Qué riesgos tiene"):
        assert f"<h2>{heading}</h2>" in page

    svg = (site / "badge" / "nimbus-labs" / "pr-review-kit.svg").read_text(encoding="utf-8")
    assert ET.fromstring(svg).get("role") == "img"


def test_json_ld_cannot_close_the_script_element() -> None:
    text = _json_ld({"description": "</script><script>alert(1)</script> & co"})
    assert "</script>" not in text and "<" not in text and "&" not in text
    assert json.loads(text)["description"].startswith("</script>")


def test_badge_and_safe_paths() -> None:
    svg = badge(87)
    assert 'aria-label="Skillscope: puntaje 87 de 100"' in svg
    assert safe_path("acme", "my.tool-1")
    assert not safe_path("acme", "..")
    assert not safe_path("../etc", "x")
    assert not safe_path("acme", "a/b")
