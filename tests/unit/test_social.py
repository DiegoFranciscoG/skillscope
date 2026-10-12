import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx

from collector.social.base import html_text, mention_key, mentions_from, run_source
from collector.social.sources import (
    Bluesky,
    DevTo,
    HackerNews,
    Mastodon,
    Reddit,
    StackExchange,
    YouTube,
)
from pipeline.clock import iso
from pipeline.config import SocialCredentials, load_settings
from tests.support import NOW, make_harness

SETTINGS = load_settings({}, offline=True, root=Path())


def _settings(**social: str) -> Any:
    return replace(SETTINGS, social=SocialCredentials(**social))


def harness(tmp: Path, routes: dict[str, Any], seen: list[httpx.Request] | None = None) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        for prefix, payload in routes.items():
            if str(request.url).startswith(prefix):
                if isinstance(payload, httpx.Response):
                    return payload
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={})

    return make_harness(tmp, handler=httpx.MockTransport(handler))


def test_helpers() -> None:
    assert mention_key("hn", "1", "A/B") == mention_key("hn", "1", "a/b")
    assert "https://github.com/a/b" in html_text('<p><a href="https://github.com/a/b">x</a></p>')
    found = mentions_from(
        "hn", "9", ["see https://github.com/a/b and github.com/c/d"], "2026-10-01", 5
    )
    assert [m.repo_id for m in found] == ["a/b"]  # only explicit https links count
    assert found[0].engagement == 5


def test_hackernews_parses_hits(tmp_path: Path) -> None:
    hit = {
        "objectID": "1",
        "created_at_i": int(NOW.timestamp()),
        "url": "https://github.com/acme/tool",
        "points": 120,
    }
    h = harness(tmp_path, {"https://hn.algolia.com": {"hits": [hit]}})
    result = run_source(HackerNews(), http=h.http, state=h.state, settings=SETTINGS, clock=h.clock)
    assert result.report.status == "ok"
    assert {m.repo_id for m in result.mentions} == {"acme/tool"}
    assert result.report.calls == HackerNews.budget
    # cadence: a second run right away is skipped
    again = run_source(HackerNews(), http=h.http, state=h.state, settings=SETTINGS, clock=h.clock)
    assert again.report.status == "skipped"
    assert "cadencia" in (again.report.reason or "")


def test_stackexchange_builds_attributed_demand_and_honours_backoff(tmp_path: Path) -> None:
    item = {
        "question_id": 7,
        "title": "Is there a skill for &quot;PR&quot; reviews?",
        "link": "https://stackoverflow.com/q/7",
        "owner": {"display_name": "Ana &amp; Co", "link": "https://stackoverflow.com/users/1"},
        "creation_date": int(NOW.timestamp()),
        "is_answered": False,
        "score": 3,
        "tags": ["claude-code", "code-review"],
        "body": '<p>like <a href="https://github.com/acme/review">this</a></p>',
    }
    seen: list[httpx.Request] = []
    h = harness(
        tmp_path,
        {
            "https://api.stackexchange.com": {
                "items": [item],
                "backoff": 600,
                "quota_remaining": 200,
            }
        },
        seen,
    )
    settings = _settings(stackexchange_key="public-app-key")
    result = run_source(
        StackExchange(), http=h.http, state=h.state, settings=settings, clock=h.clock
    )
    demand = result.demand[0]
    assert demand.title == 'Is there a skill for "PR" reviews?'
    assert demand.author == "Ana & Co"
    assert demand.url == "https://stackoverflow.com/q/7"
    assert result.mentions[0].repo_id == "acme/review"
    assert len(seen) == 1  # backoff stops further calls of the method
    assert h.state.data["schedule"]["stackexchange"] >= iso(NOW + timedelta(minutes=120))


def test_missing_credentials_skip_optional_sources(tmp_path: Path) -> None:
    h = harness(tmp_path, {})
    for source in (Reddit(), Bluesky(), YouTube()):
        result = run_source(source, http=h.http, state=h.state, settings=SETTINGS, clock=h.clock)
        assert result.report.status == "skipped"
        assert result.report.calls == 0


def test_failing_source_is_isolated(tmp_path: Path) -> None:
    h = harness(tmp_path, {"https://dev.to": httpx.Response(500)})
    result = run_source(DevTo(), http=h.http, state=h.state, settings=SETTINGS, clock=h.clock)
    assert result.report.status == "failed"
    assert result.mentions == []


def test_devto_only_fetches_new_articles(tmp_path: Path) -> None:
    routes = {
        "https://dev.to/api/articles/11": {
            "id": 11,
            "published_at": iso(NOW),
            "public_reactions_count": 4,
            "body_markdown": "uses https://github.com/acme/tool",
        },
        "https://dev.to/api/articles?": [{"id": 11, "published_at": iso(NOW)}],
    }
    seen: list[httpx.Request] = []
    h = harness(tmp_path, routes, seen)
    first = run_source(DevTo(), http=h.http, state=h.state, settings=SETTINGS, clock=h.clock)
    assert [m.repo_id for m in first.mentions] == ["acme/tool"]
    h.clock.advance(3600 * 2)
    seen.clear()
    run_source(DevTo(), http=h.http, state=h.state, settings=SETTINGS, clock=h.clock)
    assert not any("/articles/11" in str(r.url) for r in seen)


def test_mastodon_keeps_min_id_cursor(tmp_path: Path) -> None:
    statuses = [
        {
            "id": "105",
            "created_at": iso(NOW),
            "favourites_count": 2,
            "reblogs_count": 1,
            "content": '<a href="https://github.com/acme/tool">x</a>',
        }
    ]
    seen: list[httpx.Request] = []
    h = harness(tmp_path, {"https://mastodon.social": statuses}, seen)
    result = run_source(Mastodon(), http=h.http, state=h.state, settings=SETTINGS, clock=h.clock)
    assert result.mentions[0].engagement == 3
    assert h.state.cursor("mastodon")["claude"] == "105"
    h.clock.advance(3600)
    seen.clear()
    run_source(Mastodon(), http=h.http, state=h.state, settings=SETTINGS, clock=h.clock)
    assert all(r.url.params.get("min_id") == "105" for r in seen)


def test_reddit_stores_counts_only_and_never_saves_the_token(tmp_path: Path) -> None:
    post = {
        "id": "p1",
        "created_utc": int(NOW.timestamp()),
        "score": 10,
        "url": "https://github.com/acme/tool",
        "selftext": "",
        "title": "Is there a skill for invoices?",
    }
    routes = {
        "https://www.reddit.com/api/v1/access_token": {"access_token": "short-lived-token"},
        "https://oauth.reddit.com": {"data": {"children": [{"data": post}]}},
    }
    h = harness(tmp_path, routes)
    settings = _settings(
        reddit_client_id="id", reddit_client_secret="secret", reddit_user_agent="test:app:1"
    )
    result = run_source(Reddit(), http=h.http, state=h.state, settings=settings, clock=h.clock)
    assert result.report.status == "ok"
    assert result.demand[0].title is None and result.demand[0].count >= 1
    assert "invoice" in result.demand[0].text
    raw_files = list((tmp_path / "raw").rglob("*"))
    assert all(
        "short-lived-token" not in p.read_text(errors="ignore") for p in raw_files if p.is_file()
    )


def test_bluesky_and_youtube_parse_links(tmp_path: Path) -> None:
    post = {
        "uri": "at://x/1",
        "indexedAt": iso(NOW),
        "likeCount": 2,
        "repostCount": 1,
        "record": {
            "text": "nice",
            "facets": [{"features": [{"uri": "https://github.com/acme/tool"}]}],
        },
    }
    seen: list[httpx.Request] = []
    routes = {
        "https://bsky.social/xrpc/com.atproto.server.createSession": {"accessJwt": "jwt"},
        "https://bsky.social/xrpc/app.bsky.feed.searchPosts": {"posts": [post]},
        "https://www.googleapis.com/youtube/v3/search": {"items": [{"id": {"videoId": "v1"}}]},
        "https://www.googleapis.com/youtube/v3/videos": {
            "items": [
                {
                    "id": "v1",
                    "snippet": {
                        "publishedAt": iso(NOW),
                        "description": "repo https://github.com/acme/yt",
                    },
                    "statistics": {"likeCount": "9"},
                }
            ]
        },
    }
    h = harness(tmp_path, routes, seen)
    settings = _settings(
        bluesky_handle="me.bsky.social", bluesky_app_password="app-pass", youtube_api_key="yt-key"
    )
    sky = run_source(Bluesky(), http=h.http, state=h.state, settings=settings, clock=h.clock)
    assert sky.mentions[0].engagement == 3
    tube = run_source(YouTube(), http=h.http, state=h.state, settings=settings, clock=h.clock)
    assert tube.mentions[0].repo_id == "acme/yt"
    youtube_calls = [r for r in seen if "googleapis" in str(r.url)]
    assert all("yt-key" not in str(r.url) for r in youtube_calls)  # key travels in a header
    assert all(r.headers["x-goog-api-key"] == "yt-key" for r in youtube_calls)


def test_unexpected_payload_is_reported(tmp_path: Path) -> None:
    h = harness(tmp_path, {"https://hn.algolia.com": {"hits": [{"objectID": "1"}]}})
    result = run_source(HackerNews(), http=h.http, state=h.state, settings=SETTINGS, clock=h.clock)
    assert result.report.status in {"ok", "failed"}
    assert json.dumps(result.report.to_dict())
