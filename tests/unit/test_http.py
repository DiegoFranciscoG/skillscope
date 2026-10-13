from pathlib import Path
from typing import Any

import httpx
import pytest

from collector.budget import Budget
from collector.http import (
    DeadlineReachedError,
    RateLimitedError,
    RequestFailedError,
    sanitize_url,
    seconds_until_reset,
)
from tests.support import NOW, make_harness

URL = "https://api.example.test/items"


def _transport(responses: list[httpx.Response], seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responses.pop(0)

    return httpx.MockTransport(handler)


def test_etag_is_sent_and_304_served_from_raw_store(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    responses = [
        httpx.Response(200, json={"n": 1}, headers={"etag": '"abc"'}),
        httpx.Response(304, headers={"etag": '"abc"'}),
    ]
    h = make_harness(tmp_path, handler=_transport(responses, seen))
    budget = Budget("x", 5)

    first = h.http.get(URL, source="t", budget=budget, free_on_304=True)
    second = h.http.get(URL, source="t", budget=budget, free_on_304=True)

    assert first.data == {"n": 1} and not first.from_cache
    assert second.data == {"n": 1} and second.from_cache
    assert seen[1].headers["if-none-match"] == '"abc"'
    assert budget.used == 1  # the 304 was free


def test_304_counts_when_source_is_not_free(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    responses = [
        httpx.Response(200, json=[1], headers={"last-modified": "Mon, 12 Oct 2026 10:00:00 GMT"}),
        httpx.Response(304),
    ]
    h = make_harness(tmp_path, handler=_transport(responses, seen))
    budget = Budget("x", 5)
    h.http.get(URL, source="t", budget=budget)
    h.http.get(URL, source="t", budget=budget)
    assert seen[1].headers["if-modified-since"].startswith("Mon, 12 Oct")
    assert budget.used == 2


def test_retry_after_is_honoured(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    responses = [
        httpx.Response(429, headers={"retry-after": "5"}),
        httpx.Response(200, json={"ok": True}),
    ]
    h = make_harness(tmp_path, handler=_transport(responses, seen))
    result = h.http.get(URL, source="t", budget=Budget("x", 5))
    assert result.data == {"ok": True}
    assert h.clock.slept == [5.0]


def test_primary_limit_far_reset_closes_budget(tmp_path: Path) -> None:
    reset = int(NOW.timestamp()) + 3000
    responses = [
        httpx.Response(403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset)})
    ]
    h = make_harness(tmp_path, handler=_transport(responses, []))
    budget = Budget("x", 5)
    with pytest.raises(RateLimitedError):
        h.http.get(URL, source="t", budget=budget)
    assert budget.closed
    assert h.clock.slept == []  # never waits longer than allowed


def test_secondary_limit_waits_one_minute_then_retries(tmp_path: Path) -> None:
    responses = [
        httpx.Response(403, json={"message": "You have exceeded a secondary rate limit"}),
        httpx.Response(200, json={"ok": 1}),
    ]
    h = make_harness(tmp_path, handler=_transport(responses, []))
    h.http.get(URL, source="t", budget=Budget("x", 5))
    assert h.clock.slept == [60.0]


def test_plain_403_is_not_retried(tmp_path: Path) -> None:
    responses = [httpx.Response(403, json={"message": "Resource not accessible"})]
    h = make_harness(tmp_path, handler=_transport(responses, []))
    with pytest.raises(RequestFailedError) as info:
        h.http.get(URL, source="t", budget=Budget("x", 5))
    assert info.value.status == 403


def test_server_errors_back_off_then_give_up(tmp_path: Path) -> None:
    responses = [httpx.Response(502) for _ in range(4)]
    h = make_harness(tmp_path, handler=_transport(responses, []))
    with pytest.raises(RequestFailedError):
        h.http.get(URL, source="t", budget=Budget("x", 10))
    assert len(h.clock.slept) == 3
    assert h.clock.slept[0] < h.clock.slept[2]  # exponential


def test_network_error_is_retried(tmp_path: Path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json={})

    h = make_harness(tmp_path, handler=httpx.MockTransport(handler))
    h.http.get(URL, source="t", budget=Budget("x", 5))
    assert calls["n"] == 2


def test_budget_exhausted_means_no_call(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    h = make_harness(tmp_path, handler=_transport([], seen))
    with pytest.raises(RequestFailedError):
        h.http.get(URL, source="t", budget=Budget("x", 0))
    assert seen == []


def test_deadline_stops_requests(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    h = make_harness(tmp_path, handler=_transport([], seen), deadline=0)
    with pytest.raises(DeadlineReachedError):
        h.http.get(URL, source="t", budget=Budget("x", 5))
    assert seen == []


def test_min_interval_paces_calls(tmp_path: Path) -> None:
    responses = [httpx.Response(200, json={}), httpx.Response(200, json={})]
    h = make_harness(tmp_path, handler=_transport(responses, []))
    budget = Budget("search", 5, min_interval=2.1)
    h.http.get(URL, source="t", budget=budget, conditional=False)
    h.http.get(URL, source="t", budget=budget, conditional=False)
    assert h.clock.slept == [pytest.approx(2.1)]


def test_reserve_header_closes_budget(tmp_path: Path) -> None:
    responses = [
        httpx.Response(
            200, json={}, headers={"x-ratelimit-remaining": "2", "x-ratelimit-limit": "30"}
        )
    ]
    h = make_harness(tmp_path, handler=_transport(responses, []))
    budget = Budget("search", 24)
    h.http.get(URL, source="t", budget=budget)
    assert budget.closed


def test_sanitize_url_removes_secrets() -> None:
    url = sanitize_url("https://x.test/a?key=SECRET&q=1", {"access_token": "T", "page": 2})
    assert "SECRET" not in url and "access_token" not in url
    assert url == "https://x.test/a?page=2&q=1"


def test_seconds_until_reset_formats() -> None:
    now = NOW
    assert (
        seconds_until_reset(
            httpx.Headers({"x-ratelimit-reset": str(int(now.timestamp()) + 30)}), now
        )
        == 30
    )
    assert seconds_until_reset(httpx.Headers({"x-ratelimit-reset": "12"}), now) == 12
    assert (
        seconds_until_reset(httpx.Headers({"x-ratelimit-reset": "2026-10-12T12:05:00Z"}), now)
        == 300
    )
    assert seconds_until_reset(httpx.Headers({}), now) is None


def test_slow_answers_make_the_source_wait_as_long_as_they_took(tmp_path: Path) -> None:
    calls: list[float] = []
    holder: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        clock = holder["h"].clock
        calls.append(clock.monotonic())
        clock.sleep(3.0)  # the server needs 3 s to answer
        return httpx.Response(200, json={})

    h = make_harness(tmp_path, handler=httpx.MockTransport(handler))
    holder["h"] = h
    h.http.cooldown = {"github": 1.0}
    budget = Budget("x", 5)
    h.http.get(URL, source="github", budget=budget, conditional=False)
    h.http.get(URL, source="github", budget=budget, conditional=False)
    h.http.get(URL, source="other", budget=Budget("y", 5), conditional=False)

    assert calls[1] - calls[0] >= 6.0  # 3 s answering + 3 s idle
    assert calls[2] - calls[1] == 3.0  # other sources are not slowed down


def test_server_errors_can_be_handed_back_without_retrying(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    h = make_harness(tmp_path, handler=_transport([httpx.Response(502)], seen))
    with pytest.raises(RequestFailedError) as info:
        h.http.post(URL, source="t", budget=Budget("x", 5), retry_server_errors=False)
    assert info.value.status == 502
    assert len(seen) == 1
