"""One class per social source. Endpoints, limits and terms: docs/fuentes.md and #31–#47."""

from __future__ import annotations

import html
import math
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from analyzer.taxonomy import classify_category
from analyzer.text import keywords
from collector.budget import Budget
from collector.http import HttpClient, RequestFailedError
from collector.social.base import SocialSource, html_text, mentions_from
from collector.state import StateStore
from pipeline.clock import iso, parse_iso
from pipeline.config import Settings
from pipeline.models import DemandItem, Mention

QUESTION_RE = re.compile(
    r"\?\s*$|^(is there|are there|looking for|any (good )?|how (do|can|to)|need |request)", re.I
)


def _day(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%d")


def _epoch_day(value: Any) -> str:
    return _day(datetime.fromtimestamp(int(value), tz=UTC))


def _iso_day(value: Any) -> str:
    moment = parse_iso(str(value)) if value else None
    return _day(moment) if moment else _day(datetime.now(UTC))


# ---------------------------------------------------------------------------------------------
class HackerNews(SocialSource):
    """HN Search by Algolia: public, no key, 10,000 requests/hour per IP (#31)."""

    id = "hackernews"
    cadence_minutes = 30
    budget = 6
    URL = "https://hn.algolia.com/api/v1/search_by_date"
    QUERIES = (
        "claude code skill",
        "claude code plugin",
        "claude skills",
        "agent skills",
        "SKILL.md",
        "claude marketplace",
    )

    def fetch(
        self, http: HttpClient, budget: Budget, state: StateStore, settings: Settings, now: datetime
    ) -> tuple[list[Mention], list[DemandItem]]:
        cursor = state.cursor(self.id)
        since = parse_iso(cursor.get("since")) or now - timedelta(days=30)
        mentions: list[Mention] = []
        for query in self.QUERIES:
            if not budget.can_spend():
                break
            result = http.get(
                self.URL,
                source=self.id,
                budget=budget,
                params={
                    "query": query,
                    "tags": "(story,comment)",
                    "numericFilters": f"created_at_i>{int(since.timestamp())}",
                    "hitsPerPage": 100,
                },
                conditional=False,
            )
            for hit in (result.data or {}).get("hits", []):
                mentions += mentions_from(
                    self.id,
                    str(hit.get("objectID")),
                    [hit.get("url"), hit.get("story_text"), hit.get("comment_text")],
                    _epoch_day(hit.get("created_at_i", 0)),
                    int(hit.get("points") or 0),
                )
        cursor["since"] = iso(now - timedelta(minutes=30))
        return mentions, []


# ---------------------------------------------------------------------------------------------
class StackExchange(SocialSource):
    """Stack Exchange API: demand signal. Honours ``backoff``; CC BY-SA attribution (#32–#35)."""

    id = "stackexchange"
    cadence_minutes = 120
    budget = 6
    URL = "https://api.stackexchange.com/2.3/search/advanced"
    QUERIES: tuple[dict[str, str], ...] = (
        {"tagged": "claude-code"},
        {"q": "claude code"},
        {"q": "agent skill"},
        {"q": "claude plugin"},
        {"tagged": "model-context-protocol"},
    )

    def fetch(
        self, http: HttpClient, budget: Budget, state: StateStore, settings: Settings, now: datetime
    ) -> tuple[list[Mention], list[DemandItem]]:
        cursor = state.cursor(self.id)
        since = parse_iso(cursor.get("since")) or now - timedelta(days=365)
        mentions: list[Mention] = []
        demand: list[DemandItem] = []
        for query in self.QUERIES:
            if not budget.can_spend():
                break
            params: dict[str, Any] = {
                "site": "stackoverflow",
                "sort": "creation",
                "order": "desc",
                "pagesize": 100,
                "fromdate": int(since.timestamp()),
                "filter": "withbody",
                **query,
            }
            if settings.social.stackexchange_key:
                params["key"] = settings.social.stackexchange_key
            result = http.get(self.URL, source=self.id, budget=budget, params=params)
            data = result.data or {}
            for item in data.get("items", []):
                created = datetime.fromtimestamp(int(item["creation_date"]), tz=UTC)
                owner = item.get("owner") or {}
                title = html.unescape(str(item.get("title") or ""))
                tags = [str(t) for t in item.get("tags", [])]
                demand.append(
                    DemandItem(
                        source=self.id,
                        id=str(item["question_id"]),
                        created_at=iso(created),
                        text=f"{title} {' '.join(tags)}",
                        answered=bool(item.get("is_answered") or item.get("accepted_answer_id")),
                        tags=tags,
                        title=title,
                        url=str(item.get("link") or ""),
                        author=html.unescape(str(owner.get("display_name") or "anónimo")),
                        author_url=owner.get("link"),
                    )
                )
                mentions += mentions_from(
                    self.id,
                    str(item["question_id"]),
                    [html_text(item.get("body"))],
                    _day(created),
                    int(item.get("score") or 0),
                )
            backoff = int(data.get("backoff") or 0)
            if backoff:
                # The API requires waiting `backoff` seconds before calling the method again.
                state.schedule_next(self.id, max(self.cadence_minutes, math.ceil(backoff / 60)))
                break
            if int(data.get("quota_remaining", 100)) < 10:
                break
        cursor["since"] = iso(now - timedelta(hours=1))
        return mentions, _dedupe_demand(demand)


def _dedupe_demand(items: list[DemandItem]) -> list[DemandItem]:
    seen: dict[str, DemandItem] = {}
    for item in items:
        seen[f"{item.source}:{item.id}"] = item
    return list(seen.values())


# ---------------------------------------------------------------------------------------------
class Reddit(SocialSource):
    """Reddit Data API, only with approved OAuth credentials. Stores counts only (#36)."""

    id = "reddit"
    cadence_minutes = 60
    budget = 10
    TOKEN_URL = "https://www.reddit.com/api/v1/access_token"  # noqa: S105 - endpoint, not a secret
    SEARCH_URL = "https://oauth.reddit.com/r/ClaudeAI+ClaudeCode+mcp/search"
    QUERIES = ("skill", "plugin", "github.com", "is there a")

    def unavailable(self, settings: Settings) -> str | None:
        s = settings.social
        if not (s.reddit_client_id and s.reddit_client_secret and s.reddit_user_agent):
            return "sin credenciales aprobadas (Responsible Builder Policy)"
        return None

    def fetch(
        self, http: HttpClient, budget: Budget, state: StateStore, settings: Settings, now: datetime
    ) -> tuple[list[Mention], list[DemandItem]]:
        s = settings.social
        agent = str(s.reddit_user_agent)
        token = http.post(
            self.TOKEN_URL,
            source=self.id,
            budget=budget,
            form={"grant_type": "client_credentials"},
            headers={"User-Agent": agent},
            auth=(str(s.reddit_client_id), str(s.reddit_client_secret)),
            store_raw=False,
        ).data
        access = (token or {}).get("access_token")
        if not access:
            raise RequestFailedError(self.id, None, "token not granted")
        headers = {"Authorization": f"Bearer {access}", "User-Agent": agent}
        mentions: list[Mention] = []
        by_category: dict[str, Counter[str]] = defaultdict(Counter)
        counts: Counter[str] = Counter()
        for query in self.QUERIES:
            if not budget.can_spend():
                break
            result = http.get(
                self.SEARCH_URL,
                source=self.id,
                budget=budget,
                params={"q": query, "restrict_sr": 1, "sort": "new", "t": "week", "limit": 100},
                headers=headers,
                conditional=False,
            )
            for child in ((result.data or {}).get("data") or {}).get("children", []):
                post = child.get("data") or {}
                created = datetime.fromtimestamp(int(post.get("created_utc", 0)), tz=UTC)
                mentions += mentions_from(
                    self.id,
                    str(post.get("id")),
                    [post.get("url"), post.get("selftext")],
                    _day(created),
                    int(post.get("score") or 0),
                )
                title = str(post.get("title") or "")
                if QUESTION_RE.search(title.strip()):
                    category = classify_category([(title, 1.0)]).primary
                    counts[category] += 1
                    by_category[category].update(keywords(title))
        today = _day(now)
        demand = [
            DemandItem(
                source=self.id,
                id=f"{category}:{today}",
                created_at=iso(now),
                # Only single keywords are kept: no titles, authors or ids (deletion policy).
                text=" ".join(w for w, _ in by_category[category].most_common(8)),
                count=count,
            )
            for category, count in counts.items()
        ]
        return mentions, demand


# ---------------------------------------------------------------------------------------------
class DevTo(SocialSource):
    """DEV (Forem) public API. Counts only, no text is stored or shown (#42, #43, S3)."""

    id = "devto"
    cadence_minutes = 60
    budget = 12
    LIST_URL = "https://dev.to/api/articles"
    TAGS = ("claudecode", "claude", "mcp", "agentskills")

    def fetch(
        self, http: HttpClient, budget: Budget, state: StateStore, settings: Settings, now: datetime
    ) -> tuple[list[Mention], list[DemandItem]]:
        cursor = state.cursor(self.id)
        seen: list[str] = list(cursor.get("seen", []))
        fresh: list[str] = []
        for tag in self.TAGS[:2]:
            if not budget.can_spend():
                break
            listing = http.get(
                self.LIST_URL,
                source=self.id,
                budget=budget,
                params={"tag": tag, "per_page": 30},
                headers={"Accept": "application/vnd.forem.api-v1+json"},
            )
            for article in listing.data or []:
                article_id = str(article.get("id"))
                if article_id not in seen and article_id not in fresh:
                    fresh.append(article_id)
        mentions: list[Mention] = []
        for article_id in fresh:
            if not budget.can_spend():
                break
            detail = (
                http.get(
                    f"{self.LIST_URL}/{article_id}",
                    source=self.id,
                    budget=budget,
                    headers={"Accept": "application/vnd.forem.api-v1+json"},
                ).data
                or {}
            )
            mentions += mentions_from(
                self.id,
                article_id,
                [detail.get("body_markdown")],
                _iso_day(detail.get("published_at")),
                int(detail.get("public_reactions_count") or 0),
            )
            seen.append(article_id)
        cursor["seen"] = seen[-500:]
        return mentions, []


# ---------------------------------------------------------------------------------------------
class Mastodon(SocialSource):
    """Public hashtag timelines on several instances, 300 requests / 5 min each (#40, #41, #60).

    The same post reaches many instances through federation, so it is identified by its
    canonical ``uri`` and counted once. An instance that fails does not stop the others.
    """

    id = "mastodon"
    cadence_minutes = 30
    budget = 9
    INSTANCES = ("mastodon.social", "hachyderm.io", "fosstodon.org")
    TAGS = ("claudecode", "claude", "mcp")

    def fetch(
        self, http: HttpClient, budget: Budget, state: StateStore, settings: Settings, now: datetime
    ) -> tuple[list[Mention], list[DemandItem]]:
        cursor = state.cursor(self.id)
        mentions: list[Mention] = []
        failures: list[RequestFailedError] = []
        for instance in self.INSTANCES:
            for tag in self.TAGS:
                if not budget.can_spend():
                    break
                key = f"{instance}#{tag}"
                params: dict[str, Any] = {"limit": 40}
                if cursor.get(key):
                    params["min_id"] = cursor[key]
                try:
                    result = http.get(
                        f"https://{instance}/api/v1/timelines/tag/{tag}",
                        source=self.id,
                        budget=budget,
                        params=params,
                        conditional=False,
                    )
                except RequestFailedError as exc:
                    failures.append(exc)
                    break  # this instance is down or limiting us: go on with the next one
                newest = cursor.get(key)
                for status in result.data or []:
                    card = status.get("card") or {}
                    mentions += mentions_from(
                        self.id,
                        str(status.get("uri") or status.get("id")),
                        [html_text(status.get("content")), card.get("url")],
                        _iso_day(status.get("created_at")),
                        int(status.get("favourites_count") or 0)
                        + int(status.get("reblogs_count") or 0),
                    )
                    status_id = str(status.get("id"))
                    if newest is None or (status_id.isdigit() and int(status_id) > int(newest)):
                        newest = status_id
                if newest:
                    cursor[key] = newest
        if failures and len(failures) == len(self.INSTANCES):
            raise failures[0]
        return mentions, []


# ---------------------------------------------------------------------------------------------
class Lemmy(SocialSource):
    """Posts on developer-focused Lemmy instances (#61).

    Their robots.txt asks for 60 s between requests, so each run sends one search per
    instance and rotates the query between runs (cadence 60 min).
    """

    id = "lemmy"
    cadence_minutes = 60
    budget = 2
    INSTANCES = ("programming.dev", "lemmy.world")
    QUERIES = ("claude code", "mcp server", "agent skills")

    def fetch(
        self, http: HttpClient, budget: Budget, state: StateStore, settings: Settings, now: datetime
    ) -> tuple[list[Mention], list[DemandItem]]:
        cursor = state.cursor(self.id)
        turn = int(cursor.get("turn", 0))
        query = self.QUERIES[turn % len(self.QUERIES)]
        cursor["turn"] = turn + 1
        mentions: list[Mention] = []
        failures: list[RequestFailedError] = []
        for instance in self.INSTANCES:
            if not budget.can_spend():
                break
            try:
                result = http.get(
                    f"https://{instance}/api/v3/search",
                    source=self.id,
                    budget=budget,
                    params={
                        "q": query,
                        "type_": "Posts",
                        "sort": "New",
                        "listing_type": "All",
                        "limit": 50,
                    },
                    conditional=False,
                )
            except RequestFailedError as exc:
                failures.append(exc)
                continue
            for view in (result.data or {}).get("posts", []):
                post = view.get("post") or {}
                counts = view.get("counts") or {}
                mentions += mentions_from(
                    self.id,
                    str(post.get("ap_id") or post.get("id")),
                    [post.get("name"), post.get("body"), post.get("url")],
                    _iso_day(post.get("published")),
                    int(counts.get("score") or 0),
                )
        if failures and len(failures) == len(self.INSTANCES):
            raise failures[0]
        return mentions, []


# ---------------------------------------------------------------------------------------------
class Bluesky(SocialSource):
    """Bluesky search needs an account session (public AppView answers 403, E2) (#38, #39)."""

    id = "bluesky"
    cadence_minutes = 120
    budget = 4
    SESSION_URL = "https://bsky.social/xrpc/com.atproto.server.createSession"
    SEARCH_URL = "https://bsky.social/xrpc/app.bsky.feed.searchPosts"
    QUERIES = ("github.com claude skill", "github.com claude plugin", "github.com agent skills")

    def unavailable(self, settings: Settings) -> str | None:
        if not (settings.social.bluesky_handle and settings.social.bluesky_app_password):
            return "sin cuenta configurada (la búsqueda pública responde 403)"
        return None

    def fetch(
        self, http: HttpClient, budget: Budget, state: StateStore, settings: Settings, now: datetime
    ) -> tuple[list[Mention], list[DemandItem]]:
        session = (
            http.post(
                self.SESSION_URL,
                source=self.id,
                budget=budget,
                json_body={
                    "identifier": settings.social.bluesky_handle,
                    "password": settings.social.bluesky_app_password,
                },
                store_raw=False,
            ).data
            or {}
        )
        token = session.get("accessJwt")
        if not token:
            raise RequestFailedError(self.id, None, "session not created")
        cursor = state.cursor(self.id)
        since = parse_iso(cursor.get("since")) or now - timedelta(days=30)
        mentions: list[Mention] = []
        for query in self.QUERIES:
            if not budget.can_spend():
                break
            result = http.get(
                self.SEARCH_URL,
                source=self.id,
                budget=budget,
                params={"q": query, "limit": 100, "since": iso(since)},
                headers={"Authorization": f"Bearer {token}"},
                conditional=False,
            )
            for post in (result.data or {}).get("posts", []):
                record = post.get("record") or {}
                uris = [
                    feature.get("uri")
                    for facet in record.get("facets", []) or []
                    for feature in facet.get("features", []) or []
                ]
                external = ((post.get("embed") or {}).get("external") or {}).get("uri")
                mentions += mentions_from(
                    self.id,
                    str(post.get("uri")),
                    [record.get("text"), external, *uris],
                    _iso_day(post.get("indexedAt")),
                    int(post.get("likeCount") or 0) + int(post.get("repostCount") or 0),
                )
        cursor["since"] = iso(now - timedelta(minutes=30))
        return mentions, []


# ---------------------------------------------------------------------------------------------
class YouTube(SocialSource):
    """YouTube Data API with a key; at most 16 searches a day (100 allowed, #37)."""

    id = "youtube"
    cadence_minutes = 180
    budget = 3
    SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
    VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
    QUERIES = ("claude code skills", "claude code plugin")

    def unavailable(self, settings: Settings) -> str | None:
        return None if settings.social.youtube_api_key else "sin clave de API configurada"

    def fetch(
        self, http: HttpClient, budget: Budget, state: StateStore, settings: Settings, now: datetime
    ) -> tuple[list[Mention], list[DemandItem]]:
        key = str(settings.social.youtube_api_key)
        cursor = state.cursor(self.id)
        since = parse_iso(cursor.get("since")) or now - timedelta(days=30)
        ids: list[str] = []
        for query in self.QUERIES:
            if budget.remaining <= 1:
                break
            result = http.get(
                self.SEARCH_URL,
                source=self.id,
                budget=budget,
                params={
                    "part": "snippet",
                    "q": query,
                    "type": "video",
                    "order": "date",
                    "maxResults": 25,
                    "publishedAfter": iso(since),
                },
                headers={"X-Goog-Api-Key": key},
                conditional=False,
            )
            for item in (result.data or {}).get("items", []):
                video_id = (item.get("id") or {}).get("videoId")
                if video_id and video_id not in ids:
                    ids.append(str(video_id))
        mentions: list[Mention] = []
        if ids and budget.can_spend():
            result = http.get(
                self.VIDEOS_URL,
                source=self.id,
                budget=budget,
                params={"part": "snippet,statistics", "id": ",".join(ids[:50])},
                headers={"X-Goog-Api-Key": key},
                conditional=False,
            )
            for video in (result.data or {}).get("items", []):
                snippet = video.get("snippet") or {}
                stats = video.get("statistics") or {}
                mentions += mentions_from(
                    self.id,
                    str(video.get("id")),
                    [snippet.get("description")],
                    _iso_day(snippet.get("publishedAt")),
                    int(stats.get("likeCount") or 0),
                )
        cursor["since"] = iso(now - timedelta(hours=1))
        return mentions, []


ALL_SOURCES: tuple[type[SocialSource], ...] = (
    HackerNews,
    StackExchange,
    Reddit,
    DevTo,
    Mastodon,
    Lemmy,
    Bluesky,
    YouTube,
)
