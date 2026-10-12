"""Turn candidates into snapshots: metadata (GraphQL), file tree (REST) and file text (GraphQL).

Order of work inside one build:
1. Refresh metadata of already indexed repos (cheap, 40 per GraphQL point) and queue the
   ones whose head commit changed.
2. Analyze changed repos first, then new candidates by priority, until a budget or the
   deadline runs out. What is left stays in the frontier for the next build.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from analyzer.detect import Layout, layout, select_files
from collector.frontier import Frontier
from collector.github.client import GitHubClient
from collector.http import DeadlineReachedError, RequestFailedError
from collector.snapshots import SnapshotStore
from collector.state import StateStore
from pipeline.catalog import CatalogStore
from pipeline.clock import iso
from pipeline.models import RepoMeta, RepoSnapshot

log = logging.getLogger("skillscope.enrich")

META_BATCH = 40
TREE_GROUP = 8
BLOBS_PER_QUERY = 40
BLOB_BYTES_PER_QUERY = 900_000
REFRESH_SHARE = 0.3
REANALYSIS_CAP = 40  # repos re-fetched per build after an analyzer upgrade


@dataclass(slots=True)
class EnrichReport:
    refreshed: int = 0
    analyzed: int = 0
    unchanged: int = 0
    no_artifacts: int = 0
    gone: int = 0
    errors: list[str] = field(default_factory=list)


class Enricher:
    def __init__(
        self,
        gh: GitHubClient,
        state: StateStore,
        snapshots: SnapshotStore,
        frontier: Frontier,
        now: datetime,
        excluded: set[str],
        catalog: CatalogStore | None = None,
    ) -> None:
        self.gh = gh
        self.state = state
        self.snapshots = snapshots
        self.catalog = catalog
        self.frontier = frontier
        self.now = now
        self.excluded = excluded
        self.report = EnrichReport()
        self._changed: list[RepoMeta] = []

    # -- step 1 -----------------------------------------------------------------------------
    def refresh_known(self) -> None:
        graphql = self.gh.budgets.graphql
        allowance = max(1, int(graphql.remaining * REFRESH_SHARE))
        known = [
            entry
            for entry in self.state.repos().values()
            if entry.get("status") == "artifact" and entry["id"].lower() not in self.excluded
        ]
        known.sort(key=lambda e: (e.get("meta_at") or "", e["id"]))
        spent = 0
        for start in range(0, len(known), META_BATCH):
            if spent >= allowance or not graphql.can_spend():
                break
            batch = [e["id"] for e in known[start : start + META_BATCH]]
            try:
                metas = self.gh.repo_meta(batch, self.now)
            except (RequestFailedError, DeadlineReachedError) as exc:
                self.report.errors.append(str(exc))
                break
            spent += 1
            for repo_id in batch:
                meta = metas.get(repo_id.lower())
                if meta is None:
                    self._mark_gone(repo_id)
                    continue
                self.report.refreshed += 1
                entry = self.state.repo(meta.id)
                entry["meta_at"] = iso(self.now)
                entry["last_seen"] = iso(self.now)
                head_changed = bool(meta.head_oid) and meta.head_oid != entry.get("analyzed_oid")
                outdated = (
                    self.catalog is not None
                    and len(self._changed) < REANALYSIS_CAP
                    and self.catalog.needs_reanalysis(meta.id)
                )
                if head_changed or outdated:
                    self._changed.append(meta)
                if self.catalog is not None:
                    self.catalog.update_meta(meta)

    # -- step 2 -----------------------------------------------------------------------------
    def analyze(self) -> None:
        queue: list[RepoMeta] = list(self._changed)
        while True:
            if not queue:
                queue = self._next_candidates()
                if not queue:
                    return
            group, queue = queue[:TREE_GROUP], queue[TREE_GROUP:]
            if not self._analyze_group(group):
                self._requeue(group + queue)
                return

    def _next_candidates(self) -> list[RepoMeta]:
        """Pop frontier batches until one yields repos that need analysis (or budgets end)."""
        while len(self.frontier):
            if not self.gh.budgets.graphql.can_spend() or not self.gh.budgets.core.can_spend():
                return []
            batch = self.frontier.pop_batch(META_BATCH)
            ids = [str(e["id"]) for e in batch]
            try:
                metas = self.gh.repo_meta(ids, self.now)
            except (RequestFailedError, DeadlineReachedError) as exc:
                self.report.errors.append(str(exc))
                self.frontier.push_back(batch)
                return []
            out = [m for m in (self._accept(e, metas) for e in batch) if m is not None]
            if out:
                return out
        return []

    def _accept(self, entry: dict[str, Any], metas: dict[str, RepoMeta]) -> RepoMeta | None:
        meta = metas.get(str(entry["id"]).lower())
        if meta is None:
            self._mark_gone(str(entry["id"]))
            return None
        if meta.is_fork or meta.id.lower() in self.excluded:
            return None
        state = self.state.repo(meta.id)
        state["last_seen"] = iso(self.now)
        state["meta_at"] = iso(self.now)
        state["via"] = sorted(set(state.get("via", [])) | set(entry.get("via", [])))
        if meta.head_oid and meta.head_oid == state.get("analyzed_oid"):
            self.report.unchanged += 1
            return None
        return meta

    def _requeue(self, metas: list[RepoMeta]) -> None:
        for meta in metas:
            self.frontier.add(meta.id, via="requeue", stars=meta.stars, pushed_at=meta.pushed_at)

    def _analyze_group(self, metas: list[RepoMeta]) -> bool:
        """Fetch trees and files for a group. Returns False when a budget stopped the work."""
        plans: list[tuple[RepoMeta, list[Any], bool, list[str]]] = []
        for index, meta in enumerate(metas):
            if not meta.head_oid:
                self._mark_status(meta, "no_artifact")
                continue
            if not self.gh.budgets.core.can_spend():
                self._requeue(metas[index:])
                break
            try:
                tree = self.gh.tree(meta.id, meta.head_oid)
            except DeadlineReachedError:
                self._requeue(metas[index:])
                return False
            except RequestFailedError as exc:
                if exc.status in (404, 409):
                    self._mark_status(meta, "no_artifact")
                    continue
                self.report.errors.append(str(exc))
                self._requeue(metas[index:])
                return False
            lay = layout(tree.entries)
            if not lay.has_artifacts() and not _worth_fetching(meta, lay):
                self._mark_status(meta, "no_artifact")
                self.report.no_artifacts += 1
                continue
            sizes = {e.path: e.size for e in tree.entries}
            plans.append((meta, tree.entries, tree.truncated, select_files(lay, sizes)))
        if not plans:
            return self.gh.budgets.core.can_spend()
        texts = self._fetch_texts(plans)
        if texts is None:
            self._requeue([p[0] for p in plans])
            return False
        for meta, entries, truncated, wanted in plans:
            files = {
                p: texts[(meta.id.lower(), p)] for p in wanted if (meta.id.lower(), p) in texts
            }
            state = self.state.repo(meta.id)
            snapshot = RepoSnapshot(
                meta=meta,
                tree=list(entries),
                tree_truncated=truncated,
                files=files,
                via=list(state.get("via", [])),
                fetched_at=iso(self.now),
            )
            self.snapshots.save(snapshot)
            state["analyzed_oid"] = meta.head_oid
            state["status"] = "artifact"
            state["analyzed_at"] = iso(self.now)
            self.report.analyzed += 1
        return True

    def _fetch_texts(
        self, plans: list[tuple[RepoMeta, list[Any], bool, list[str]]]
    ) -> dict[tuple[str, str], str] | None:
        requests: list[tuple[str, str, str]] = []
        sizes: list[int] = []
        for meta, entries, _truncated, wanted in plans:
            size_of = {e.path: e.size for e in entries}
            for path in wanted:
                requests.append((meta.id, str(meta.head_oid), path))
                sizes.append(size_of.get(path, 0))
        texts: dict[tuple[str, str], str] = {}
        chunk: list[tuple[str, str, str]] = []
        chunk_bytes = 0
        for request, size in [*zip(requests, sizes, strict=True), (None, 0)]:
            flush = request is None or (
                chunk
                and (len(chunk) >= BLOBS_PER_QUERY or chunk_bytes + size > BLOB_BYTES_PER_QUERY)
            )
            if flush and chunk:
                if not self.gh.budgets.graphql.can_spend():
                    return None
                try:
                    texts.update(self.gh.blobs(chunk))
                except (RequestFailedError, DeadlineReachedError) as exc:
                    self.report.errors.append(str(exc))
                    return None
                chunk, chunk_bytes = [], 0
            if request is not None:
                chunk.append(request)
                chunk_bytes += size
        return texts

    # -- helpers ----------------------------------------------------------------------------
    def _mark_status(self, meta: RepoMeta, status: str) -> None:
        state = self.state.repo(meta.id)
        state["status"] = status
        state["analyzed_oid"] = meta.head_oid
        state["analyzed_at"] = iso(self.now)
        if status != "artifact":
            self.snapshots.delete(meta.id)
            if self.catalog is not None:
                self.catalog.delete(meta.id)

    def _mark_gone(self, repo_id: str) -> None:
        state = self.state.known_repo(repo_id)
        if state is None:
            return
        misses = int(state.get("misses", 0)) + 1
        state["misses"] = misses
        if misses >= 2:
            state["status"] = "gone"
            self.snapshots.delete(repo_id)
            if self.catalog is not None:
                self.catalog.delete(repo_id)
            self.report.gone += 1

    def run(self) -> EnrichReport:
        self.refresh_known()
        self.analyze()
        return self.report


def _worth_fetching(meta: RepoMeta, lay: Layout) -> bool:
    """Repos without skill files that still belong in the index: awesome lists and MCP servers."""
    topics = {t.lower() for t in meta.topics}
    name = meta.name.lower()
    if lay.readme and ("awesome" in name or "awesome" in topics or "awesome-list" in topics):
        return True
    has_package = bool(lay.package_json or lay.pyproject)
    mcp_hint = "mcp" in name or bool(topics & {"mcp", "mcp-server", "model-context-protocol"})
    return has_package and mcp_hint
