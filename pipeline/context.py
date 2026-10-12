"""Wiring shared by every command: clock, HTTP client, state and stores."""

from __future__ import annotations

from dataclasses import dataclass, replace

import httpx

from collector.http import HttpClient
from collector.rawstore import RawStore
from collector.snapshots import SnapshotStore
from collector.state import StateStore
from pipeline.clock import Clock, InstantClock, SystemClock
from pipeline.config import Settings
from pipeline.sample_api import SampleApi

USER_AGENT = "skillscope/0.1 (+https://github.com/DiegoFranciscoG/skillscope)"
OFFLINE_TOKEN = "offline-sample"  # noqa: S105 - placeholder for the in-memory sample API


@dataclass(slots=True)
class Context:
    settings: Settings
    clock: Clock
    http: HttpClient
    state: StateStore
    raw: RawStore
    snapshots: SnapshotStore
    sample_api: SampleApi | None

    def close(self) -> None:
        self.http.client.close()


def open_context(settings: Settings, clock: Clock | None = None) -> Context:
    clock = clock or (InstantClock() if settings.offline else SystemClock())
    sample_api: SampleApi | None = None
    if settings.offline:
        sample_api = SampleApi(settings.samples_dir, clock)
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
    )
    snapshots = SnapshotStore(settings.state_dir / "snapshots")
    return Context(settings, clock, http, state, raw, snapshots, sample_api)
