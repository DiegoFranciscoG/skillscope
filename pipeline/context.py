"""Wiring shared by every command: clock, HTTP client, state and stores."""

from __future__ import annotations

from dataclasses import dataclass, replace

import httpx

from collector.http import HttpClient
from collector.rawstore import RawStore
from collector.snapshots import SnapshotStore
from collector.state import StateStore
from pipeline.catalog import CatalogStore
from pipeline.clock import Clock, InstantClock, SystemClock
from pipeline.config import Settings
from pipeline.sample_api import SampleApi

USER_AGENT = "skillscope/0.1 (+https://github.com/DiegoFranciscoG/skillscope)"
OFFLINE_TOKEN = "offline-sample"  # noqa: S105 - placeholder for the in-memory sample API
GITHUB_COOLDOWN = 0.5  # idle 0.5 × response time: server CPU ≤ 2/3 of wall time (≤ 40 s/min)


@dataclass(slots=True)
class Context:
    settings: Settings
    clock: Clock
    http: HttpClient
    state: StateStore
    raw: RawStore
    snapshots: SnapshotStore
    catalog: CatalogStore
    sample_api: SampleApi | None

    def close(self) -> None:
        self.http.client.close()


def open_context(
    settings: Settings, clock: Clock | None = None, sample_api: SampleApi | None = None
) -> Context:
    clock = clock or (InstantClock() if settings.offline else SystemClock())
    if settings.offline and sample_api is None:
        sample_api = SampleApi(
            settings.samples_dir, clock, limits={"search": 1000, "code_search": 1000}
        )
    if settings.offline and sample_api is not None:
        transport: httpx.BaseTransport = sample_api.transport()
        settings = replace(settings, github_token=OFFLINE_TOKEN)
    else:
        transport = httpx.HTTPTransport(retries=0)
    client = httpx.Client(
        transport=transport,
        timeout=httpx.Timeout(20.0),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
    state = StateStore(settings.state_dir / "state.json", clock)
    raw = RawStore(settings.raw_dir, clock)
    http = HttpClient(
        client=client,
        state=state,
        raw=raw,
        clock=clock,
        deadline=clock.monotonic() + settings.max_seconds,
        # GitHub: server CPU per minute is capped; stay idle as long as each answer took.
        cooldown={"github": GITHUB_COOLDOWN},
    )
    snapshots = SnapshotStore(settings.state_dir / "snapshots")
    catalog = CatalogStore(settings.state_dir / "catalog")
    return Context(settings, clock, http, state, raw, snapshots, catalog, sample_api)
