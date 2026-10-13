"""Full build against the sample API: collect → social → analyze → index → files."""

import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from indexer.embeddings import decode
from pipeline.build import BuildResult, run_build
from pipeline.clock import FakeClock
from pipeline.config import load_settings
from pipeline.context import open_context
from pipeline.sample_api import SampleApi
from tests.support import NOW, ROOT, SAMPLES


def build(tmp: Path, clock: FakeClock | None = None, **api: Any) -> tuple[BuildResult, Path]:
    clock = clock or FakeClock(NOW)
    settings = load_settings({}, offline=True, root=tmp)
    settings = replace(settings, samples_dir=SAMPLES, config_dir=ROOT / "config")
    sample_api = SampleApi(SAMPLES, clock, limits={"search": 1000, "code_search": 1000}, **api)
    ctx = open_context(settings, clock, sample_api)
    try:
        result = run_build(ctx, tmp / "site", ROOT)
    finally:
        ctx.close()
    return result, tmp / "site" / "data"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def test_offline_build_writes_consistent_site_data(tmp_path: Path) -> None:
    result, data = build(tmp_path)
    index = load(data / "index.json")
    assert re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{7}", index["build_id"])
    assert index["built_at"].startswith("2026-10-12T12:")  # time after collection, not before
    items = index["items"]
    assert len(items) == result.published == 43
    scores = [i["score"] for i in items]
    assert scores == sorted(scores, reverse=True)
    assert all(len(i["summary"]) <= 320 for i in items)
    assert all(i["sample"] for i in items)
    statuses = {s["id"]: s.get("status", "ok") for s in index["sources"]}
    assert statuses["github"] == "ok" and statuses["reddit"] == "skipped"

    # every item has a detail record in the shard named in index.json → files
    for item in items:
        shard = load(data / "detail" / f"{item['category']}.json")
        detail = shard["items"][item["id"]]
        assert detail["links"]["repo"] is None  # fictional repos never link to GitHub
        assert detail["score"]["total"] == item["score"]
    assert index["files"]["embeddings"].startswith("data/embeddings.bin?v=")

    # embeddings are aligned with the published items
    meta = load(data / "embeddings.json")
    assert meta["ids"] == [i["id"] for i in items]
    dims, docs, _scales, terms = decode((data / "embeddings.bin").read_bytes())
    assert dims == meta["dims"] > 0
    assert docs.shape[0] == len(items) and terms.shape[0] == len(meta["terms"])

    demand = load(data / "demand.json")
    gaps = {g["label"] for g in demand["gaps"]}
    assert {"cobol, mainframe, migration", "excel, vba, macros"} <= gaps
    assert all(i["author"] and i["url"] for i in demand["items"])
    # Fictional questions never point at real people or real Stack Overflow posts.
    assert demand["sample"] is True and "ficticias" in demand["attribution"]
    for question in demand["items"]:
        assert question["url"].startswith("https://example.com/")
        assert (question["author_url"] or "https://example.com/").startswith("https://example.com/")

    signals = load(data / "signals.json")
    assert len(signals["days"]) == 30
    assert signals["repos"]["demo_nimbus-labs/pr-review-kit"]["stars"][-1] == 8200


def test_published_files_hold_no_emails_or_tokens(tmp_path: Path) -> None:
    _, data = build(tmp_path)
    text = "\n".join(p.read_text(encoding="utf-8") for p in data.rglob("*.json"))
    assert "@example.com" not in text  # manifest emails are dropped
    assert "offline-sample" not in text
    assert not re.search(r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_|AIza[0-9A-Za-z_-]{20,}", text)


def test_site_still_builds_when_a_social_source_is_down(tmp_path: Path) -> None:
    """Acceptance: a failing social source never breaks the build."""
    result, data = build(tmp_path, fail_hosts={"hn.algolia.com", "dev.to"})
    statuses = {s["id"]: s.get("status", "ok") for s in result.sources}
    assert statuses["hackernews"] == "failed"
    assert statuses["devto"] == "failed"
    assert statuses["github"] == "ok"
    assert len(load(data / "index.json")["items"]) == 43


def test_second_build_reuses_cached_analysis(tmp_path: Path) -> None:
    clock = FakeClock(NOW)
    first, _ = build(tmp_path, clock)
    clock.advance(15 * 60)
    second, data = build(tmp_path, clock)
    analysis = second.sources[0]["details"]["analysis"]
    assert analysis["analyzed"] == 0  # nothing changed, nothing re-analyzed
    assert second.build_id != first.build_id
    assert len(load(data / "index.json")["items"]) == 43
