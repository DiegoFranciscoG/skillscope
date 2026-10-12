"""HTTP client shared by every source.

Responsibilities, in order:
1. Refuse to call when the build deadline or the source budget is reached.
2. Pace calls (minimum interval per budget) and send them one at a time.
3. Send ``If-None-Match`` / ``If-Modified-Since`` and serve 304 answers from the raw store.
4. Read rate-limit headers and close the budget before the API reserve is touched.
5. Retry transient failures with exponential back-off and jitter; honour ``Retry-After``.
"""

from __future__ import annotations

import json
import logging
import random
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from collector.budget import Budget, BudgetExhaustedError
from collector.rawstore import RawStore
from collector.state import StateStore
from pipeline.clock import Clock, parse_iso

log = logging.getLogger("skillscope.http")

SECRET_PARAMS = frozenset(
    {"key", "access_token", "api_key", "apikey", "token", "client_secret", "password"}
)
RETRYABLE_STATUS = frozenset({500, 502, 503, 504})


class RequestFailedError(Exception):
    def __init__(self, source: str, status: int | None, reason: str) -> None:
        super().__init__(f"{source}: {reason} (status {status})")
        self.source = source
        self.status = status
        self.reason = reason


class RateLimitedError(RequestFailedError):
    pass


class DeadlineReachedError(RequestFailedError):
    pass


@dataclass(slots=True)
class HttpResult:
    status: int
    data: Any
    headers: httpx.Headers
    from_cache: bool
    url: str


def sanitize_url(url: str, params: Mapping[str, Any] | None = None) -> str:
    """URL used for logs and cache keys: query sorted, secret parameters removed."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k.lower() not in SECRET_PARAMS]
    if params:
        query += [(k, str(v)) for k, v in params.items() if k.lower() not in SECRET_PARAMS]
    query.sort()
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _parse_body(body: bytes) -> Any:
    if not body:
        return None
    text = body.decode("utf-8", errors="replace")
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return text


def _int_header(headers: httpx.Headers, name: str) -> int | None:
    value = headers.get(name)
    if value is None:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def seconds_until_reset(headers: httpx.Headers, now: datetime) -> float | None:
    """Understands epoch seconds (GitHub), relative seconds (Reddit) and ISO dates (Mastodon)."""
    raw = headers.get("x-ratelimit-reset") or headers.get("ratelimit-reset")
    if raw is None:
        return None
    try:
        number = float(raw)
    except ValueError:
        moment = parse_iso(raw)
        return None if moment is None else max(0.0, (moment - now).total_seconds())
    if number > 1_000_000_000:
        return max(0.0, number - now.timestamp())
    return max(0.0, number)


class HttpClient:
    def __init__(
        self,
        *,
        client: httpx.Client,
        state: StateStore,
        raw: RawStore,
        clock: Clock,
        deadline: float,
        rng: random.Random | None = None,
        max_retries: int = 3,
        max_wait: float = 90.0,
    ) -> None:
        self.client = client
        self.state = state
        self.raw = raw
        self.clock = clock
        self.deadline = deadline
        self.rng = rng or random.Random(0)  # noqa: S311 - jitter, not cryptography
        self.max_retries = max_retries
        self.max_wait = max_wait

    # -- public -----------------------------------------------------------------------------
    def get(
        self,
        url: str,
        *,
        source: str,
        budget: Budget,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        conditional: bool = True,
        free_on_304: bool = False,
    ) -> HttpResult:
        return self._request(
            "GET",
            url,
            source=source,
            budget=budget,
            params=params,
            headers=headers,
            body=None,
            conditional=conditional,
            free_on_304=free_on_304,
            cost=1,
        )

    def post(
        self,
        url: str,
        *,
        source: str,
        budget: Budget,
        json_body: Any = None,
        form: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        cost: int = 1,
    ) -> HttpResult:
        body: dict[str, Any] = {"json": json_body} if form is None else {"data": dict(form)}
        return self._request(
            "POST",
            url,
            source=source,
            budget=budget,
            params=None,
            headers=headers,
            body=body,
            conditional=False,
            free_on_304=False,
            cost=cost,
        )

    def remaining_seconds(self) -> float:
        return self.deadline - self.clock.monotonic()

    # -- internals --------------------------------------------------------------------------
    def _pace(self, budget: Budget) -> None:
        if budget.min_interval and budget.last_call_at is not None:
            wait = budget.last_call_at + budget.min_interval - self.clock.monotonic()
            if wait > 0:
                self.clock.sleep(wait)
        budget.last_call_at = self.clock.monotonic()

    def _backoff(self, attempt: int) -> float:
        return float(min(30.0, (2**attempt) * self.rng.uniform(0.5, 1.5)))

    def _wait_or_fail(self, wait: float, source: str, budget: Budget, reason: str) -> None:
        if wait > self.max_wait or wait >= self.remaining_seconds():
            budget.close(reason)
            raise RateLimitedError(source, 429, reason)
        log.warning("%s: %s, waiting %.0fs", source, reason, wait)
        self.clock.sleep(wait)

    def _request(
        self,
        method: str,
        url: str,
        *,
        source: str,
        budget: Budget,
        params: Mapping[str, Any] | None,
        headers: Mapping[str, str] | None,
        body: dict[str, Any] | None,
        conditional: bool,
        free_on_304: bool,
        cost: int,
    ) -> HttpResult:
        key = f"{method} {sanitize_url(url, params)}"
        cached = self.state.resource(key) if conditional else None
        send_headers = dict(headers or {})
        if cached:
            if cached.get("etag"):
                send_headers["If-None-Match"] = str(cached["etag"])
            elif cached.get("last_modified"):
                send_headers["If-Modified-Since"] = str(cached["last_modified"])

        attempt = 0
        while True:
            if self.remaining_seconds() <= 0:
                raise DeadlineReachedError(source, None, "build deadline reached")
            try:
                budget.ensure(cost)
            except BudgetExhaustedError as exc:
                raise RequestFailedError(source, None, str(exc)) from exc
            self._pace(budget)
            try:
                response = self.client.request(
                    method, url, params=params, headers=send_headers, **(body or {})
                )
            except httpx.HTTPError as exc:
                budget.spend(cost)
                if attempt >= self.max_retries:
                    raise RequestFailedError(source, None, f"network error: {exc}") from exc
                self.clock.sleep(self._backoff(attempt))
                attempt += 1
                continue

            status = response.status_code
            budget.observe(
                _int_header(response.headers, "x-ratelimit-remaining"),
                _int_header(response.headers, "x-ratelimit-limit"),
            )

            if status == 304 and cached:
                if not free_on_304:
                    budget.spend(cost)
                payload = self.raw.load(str(cached.get("body_sha256", "")))
                if payload is not None:
                    return HttpResult(304, _parse_body(payload), response.headers, True, url)
                # Cache object was pruned: ask again without the conditional header.
                send_headers.pop("If-None-Match", None)
                send_headers.pop("If-Modified-Since", None)
                cached = None
                continue

            budget.spend(cost)

            if 200 <= status < 300:
                content = response.content
                sha = self.raw.save(source, sanitize_url(url, params), status, content)
                if conditional:
                    self.state.remember(
                        key,
                        etag=response.headers.get("etag"),
                        last_modified=response.headers.get("last-modified"),
                        sha=sha,
                    )
                return HttpResult(status, _parse_body(content), response.headers, False, url)

            if status in (403, 429):
                self._handle_limited(response, source, budget, attempt)
                attempt += 1
                continue

            if status in RETRYABLE_STATUS and attempt < self.max_retries:
                self.clock.sleep(self._backoff(attempt))
                attempt += 1
                continue

            raise RequestFailedError(source, status, f"HTTP {status} for {sanitize_url(url)}")

    def _handle_limited(
        self, response: httpx.Response, source: str, budget: Budget, attempt: int
    ) -> None:
        headers = response.headers
        now = self.clock.now().astimezone(UTC)
        retry_after = headers.get("retry-after")
        if retry_after is not None:
            try:
                wait = float(retry_after)
            except ValueError:
                moment = parse_iso(retry_after)
                wait = 60.0 if moment is None else max(0.0, (moment - now).total_seconds())
            self._wait_or_fail(wait, source, budget, "retry-after")
            return
        if headers.get("x-ratelimit-remaining") == "0":
            reset = seconds_until_reset(headers, now)
            self._wait_or_fail(60.0 if reset is None else reset + 1, source, budget, "rate limit")
            return
        text = response.text.lower()
        if "rate limit" in text or response.status_code == 429:
            if attempt >= self.max_retries:
                budget.close("secondary rate limit")
                raise RateLimitedError(source, response.status_code, "secondary rate limit")
            self._wait_or_fail(60.0 * (2**attempt), source, budget, "secondary rate limit")
            return
        raise RequestFailedError(source, response.status_code, "forbidden")
