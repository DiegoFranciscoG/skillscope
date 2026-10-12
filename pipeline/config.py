"""Settings loaded from environment variables. Critical values fail fast, never default."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


class ConfigError(Exception):
    """Raised when a required setting is missing or invalid; the build must not start."""


@dataclass(frozen=True, slots=True)
class Budgets:
    """Maximum calls (or GraphQL points) a single build may spend per resource."""

    rest: int = 140
    graphql: int = 120
    search: int = 24
    code_search: int = 5
    npm: int = 30


@dataclass(frozen=True, slots=True)
class SocialCredentials:
    stackexchange_key: str | None = field(default=None, repr=False)
    reddit_client_id: str | None = field(default=None, repr=False)
    reddit_client_secret: str | None = field(default=None, repr=False)
    reddit_user_agent: str | None = None
    bluesky_handle: str | None = None
    bluesky_app_password: str | None = field(default=None, repr=False)
    youtube_api_key: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class Settings:
    offline: bool
    site_url: str
    state_dir: Path
    raw_dir: Path
    out_dir: Path
    samples_dir: Path
    config_dir: Path
    github_token: str | None = field(default=None, repr=False)
    repository: str | None = None
    budgets: Budgets = field(default_factory=Budgets)
    max_seconds: int = 360
    index_max: int = 6000
    social: SocialCredentials = field(default_factory=SocialCredentials)


_REPO_RE = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")
LOCAL_SITE_URL = "http://localhost:8080/"
# The offline build talks to the in-memory sample API: no real quota is spent.
OFFLINE_BUDGETS = Budgets(rest=500, graphql=500, search=200, code_search=50, npm=50)


def _int(env: Mapping[str, str], key: str, default: int, low: int, high: int) -> int:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} debe ser un entero (recibido: {raw!r})") from exc
    if not low <= value <= high:
        raise ConfigError(f"{key} debe estar entre {low} y {high} (recibido: {value})")
    return value


def _opt(env: Mapping[str, str], key: str) -> str | None:
    value = env.get(key, "").strip()
    return value or None


def normalize_site_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError(f"SKILLSCOPE_SITE_URL no es una URL http(s) válida: {url!r}")
    return url if url.endswith("/") else url + "/"


def load_settings(
    env: Mapping[str, str],
    *,
    offline: bool,
    root: Path,
    out_dir: Path | None = None,
) -> Settings:
    """Read settings from ``env``. Online builds need a token and a public site URL."""
    token = None if offline else _opt(env, "GITHUB_TOKEN")
    site = _opt(env, "SKILLSCOPE_SITE_URL")
    if not offline:
        missing = [k for k, v in (("GITHUB_TOKEN", token), ("SKILLSCOPE_SITE_URL", site)) if not v]
        if missing:
            raise ConfigError(
                "Faltan variables obligatorias para el modo en línea: " + ", ".join(missing)
            )
    site_url = normalize_site_url(site) if site else LOCAL_SITE_URL

    repository = _opt(env, "SKILLSCOPE_REPOSITORY") or _opt(env, "GITHUB_REPOSITORY")
    if repository and not _REPO_RE.match(repository):
        raise ConfigError(f"SKILLSCOPE_REPOSITORY debe tener la forma owner/repo: {repository!r}")

    mode = "sample" if offline else "live"
    budgets = (
        OFFLINE_BUDGETS
        if offline
        else Budgets(
            rest=_int(env, "SKILLSCOPE_BUDGET_REST", 140, 0, 5000),
            graphql=_int(env, "SKILLSCOPE_BUDGET_GRAPHQL", 120, 0, 5000),
            search=_int(env, "SKILLSCOPE_BUDGET_SEARCH", 24, 0, 300),
            code_search=_int(env, "SKILLSCOPE_BUDGET_CODE_SEARCH", 5, 0, 100),
            npm=_int(env, "SKILLSCOPE_BUDGET_NPM", 30, 0, 500),
        )
    )
    # Offline builds never read credentials: they only talk to the in-memory sample API.
    social = (
        SocialCredentials()
        if offline
        else SocialCredentials(
            stackexchange_key=_opt(env, "STACKEXCHANGE_KEY"),
            reddit_client_id=_opt(env, "REDDIT_CLIENT_ID"),
            reddit_client_secret=_opt(env, "REDDIT_CLIENT_SECRET"),
            reddit_user_agent=_opt(env, "REDDIT_USER_AGENT"),
            bluesky_handle=_opt(env, "BLUESKY_HANDLE"),
            bluesky_app_password=_opt(env, "BLUESKY_APP_PASSWORD"),
            youtube_api_key=_opt(env, "YOUTUBE_API_KEY"),
        )
    )
    return Settings(
        offline=offline,
        site_url=site_url,
        state_dir=root / "data" / "state" / mode,
        raw_dir=root / "data" / "raw" / mode,
        out_dir=out_dir or root / "site",
        samples_dir=root / "data" / "samples",
        config_dir=root / "config",
        github_token=token,
        repository=repository,
        budgets=budgets,
        max_seconds=_int(env, "SKILLSCOPE_MAX_SECONDS", 360, 30, 3000),
        index_max=_int(env, "SKILLSCOPE_INDEX_MAX", 6000, 10, 50000),
        social=social,
    )
