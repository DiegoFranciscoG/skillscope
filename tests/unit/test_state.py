import json
from pathlib import Path

import pytest

from collector.rawstore import RawStore
from collector.state import StateStore
from pipeline.migrations import STATE_VERSION, migrate
from tests.support import make_harness


def test_migrate_empty_and_v0() -> None:
    assert migrate(None)["schema_version"] == STATE_VERSION
    old = {"etags": {"GET x": {"etag": "1"}}}
    new = migrate(old)
    assert new["resources"] == {"GET x": {"etag": "1"}}
    assert new["schema_version"] == 1 and new["frontier"] == []


def test_migrate_refuses_future_versions() -> None:
    with pytest.raises(ValueError, match="newer"):
        migrate({"schema_version": 99})


def test_state_roundtrip_and_schedule(tmp_path: Path) -> None:
    h = make_harness(tmp_path)
    h.state.remember("GET a", etag='"1"', last_modified=None, sha="abc")
    assert h.state.is_due("hn")
    h.state.schedule_next("hn", 30)
    assert not h.state.is_due("hn")
    h.clock.advance(31 * 60)
    assert h.state.is_due("hn")
    h.state.repo("Owner/Repo")["status"] = "artifact"
    h.state.save()
    loaded = StateStore(tmp_path / "state.json", h.clock)
    assert loaded.resource("GET a") is not None
    assert loaded.known_repo("owner/repo") == {
        "id": "Owner/Repo",
        "first_seen": "2026-10-12T12:31:00Z",
        "status": "artifact",
    }
    assert loaded.referenced_objects() == {"abc"}


def test_rawstore_is_content_addressed(tmp_path: Path) -> None:
    h = make_harness(tmp_path)
    raw = RawStore(tmp_path / "raw", h.clock)
    sha1 = raw.save("github", "https://x/a", 200, b'{"a":1}')
    sha2 = raw.save("github", "https://x/b", 200, b'{"a":1}')
    assert sha1 == sha2
    assert raw.load(sha1) == b'{"a":1}'
    manifest = (tmp_path / "raw" / "2026-10-12" / "manifest.jsonl").read_text().splitlines()
    assert len(manifest) == 2 and json.loads(manifest[0])["sha256"] == sha1
    assert raw.load("missing") is None
    assert raw.prune(keep={sha1}, max_age_days=0) == 0
    assert raw.prune(keep=set(), max_age_days=-1) == 1
