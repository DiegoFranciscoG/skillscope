"""Content-addressed store of raw API responses.

Bodies are saved once under ``objects/<sha[:2]>/<sha>`` and every fetch is logged with its
date in ``<YYYY-MM-DD>/manifest.jsonl``. That makes any build reproducible and lets a 304
answer be served from disk.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from pipeline.clock import Clock, iso
from pipeline.jsonio import write_bytes


class RawStore:
    def __init__(self, base: Path, clock: Clock) -> None:
        self.base = base
        self.clock = clock

    def _object_path(self, sha: str) -> Path:
        return self.base / "objects" / sha[:2] / sha

    def save(self, source: str, url: str, status: int, body: bytes) -> str:
        sha = hashlib.sha256(body).hexdigest()
        target = self._object_path(sha)
        if not target.exists():
            write_bytes(target, body)
        day = self.clock.now().strftime("%Y-%m-%d")
        manifest = self.base / day / "manifest.jsonl"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "source": source,
            "url": url,
            "status": status,
            "sha256": sha,
            "fetched_at": iso(self.clock.now()),
            "bytes": len(body),
        }
        with manifest.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return sha

    def load(self, sha: str) -> bytes | None:
        path = self._object_path(sha)
        if not path.exists():
            return None
        return path.read_bytes()

    def prune(self, keep: set[str], max_age_days: int) -> int:
        """Delete objects older than ``max_age_days`` that no ETag still points to."""
        objects = self.base / "objects"
        if not objects.exists():
            return 0
        cutoff = time.time() - max_age_days * 86400
        removed = 0
        for path in objects.glob("*/*"):
            if path.name in keep:
                continue
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        return removed
