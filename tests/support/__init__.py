"""Shared helpers for the test suite."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from collector.http import HttpClient
from collector.rawstore import RawStore
from collector.state import StateStore
from pipeline.clock import FakeClock
from pipeline.sample_api import SampleApi

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "data" / "samples"
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


@dataclass
class Harness:
    clock: FakeClock
    state: StateStore
    raw: RawStore
    http: HttpClient
    api: SampleApi | None
    client: httpx.Client


def make_harness(
    tmp: Path,
    *,
    handler: httpx.MockTransport | None = None,
    api: SampleApi | None = None,
    deadline: float = 600.0,
    clock: FakeClock | None = None,
) -> Harness:
    clock = clock or FakeClock(NOW)
    if api is None and handler is None:
        api = SampleApi(SAMPLES, clock)
    transport = handler or (api.transport() if api else None)
    client = httpx.Client(transport=transport)
    state = StateStore(tmp / "state.json", clock)
    raw = RawStore(tmp / "raw", clock)
    http = HttpClient(
        client=client, state=state, raw=raw, clock=clock, deadline=clock.monotonic() + deadline
    )
    return Harness(clock, state, raw, http, api, client)
