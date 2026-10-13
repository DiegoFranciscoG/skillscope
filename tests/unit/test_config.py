from pathlib import Path

import pytest

from pipeline.config import ConfigError, load_settings, normalize_site_url


def test_online_mode_fails_fast_without_token() -> None:
    with pytest.raises(ConfigError, match="SKILLSCOPE_GITHUB_TOKEN"):
        load_settings({"SKILLSCOPE_SITE_URL": "https://x.github.io/s/"}, offline=False, root=Path())


def test_online_mode_fails_fast_without_site_url() -> None:
    with pytest.raises(ConfigError, match="SKILLSCOPE_SITE_URL"):
        load_settings({"SKILLSCOPE_GITHUB_TOKEN": "t"}, offline=False, root=Path())


def test_offline_mode_needs_no_secrets() -> None:
    settings = load_settings({}, offline=True, root=Path("/repo"))
    assert settings.github_token is None
    assert settings.site_url == "http://localhost:8080/"
    assert settings.state_dir == Path("/repo/data/state/sample")


def test_offline_mode_ignores_credentials_in_the_environment() -> None:
    env = {
        "SKILLSCOPE_GITHUB_TOKEN": "real",
        "SKILLSCOPE_YOUTUBE_API_KEY": "real-key",
        "SKILLSCOPE_STACKEXCHANGE_KEY": "k",
    }
    settings = load_settings(env, offline=True, root=Path())
    assert settings.github_token is None
    assert settings.social.youtube_api_key is None
    assert settings.social.stackexchange_key is None


def test_token_never_appears_in_repr() -> None:
    settings = load_settings(
        {"SKILLSCOPE_GITHUB_TOKEN": "ghp_should_not_leak", "SKILLSCOPE_SITE_URL": "https://a.b/c"},
        offline=False,
        root=Path(),
    )
    assert "ghp_should_not_leak" not in repr(settings)
    assert settings.site_url == "https://a.b/c/"


ONLINE = {"SKILLSCOPE_GITHUB_TOKEN": "t", "SKILLSCOPE_SITE_URL": "https://a.b/"}


def test_budgets_are_validated() -> None:
    with pytest.raises(ConfigError, match="entero"):
        load_settings(ONLINE | {"SKILLSCOPE_BUDGET_REST": "many"}, offline=False, root=Path())
    with pytest.raises(ConfigError, match="entre"):
        load_settings(ONLINE | {"SKILLSCOPE_BUDGET_SEARCH": "999"}, offline=False, root=Path())
    settings = load_settings(ONLINE | {"SKILLSCOPE_BUDGET_REST": "700"}, offline=False, root=Path())
    assert settings.budgets.rest == 700
    assert settings.state_dir == Path("data/state/live")


def test_repository_format() -> None:
    with pytest.raises(ConfigError):
        load_settings({"GITHUB_REPOSITORY": "not a repo"}, offline=True, root=Path())
    assert (
        load_settings({"GITHUB_REPOSITORY": "a/b"}, offline=True, root=Path()).repository == "a/b"
    )


def test_site_url_validation() -> None:
    with pytest.raises(ConfigError):
        normalize_site_url("ftp://x")
    assert normalize_site_url("https://x.dev") == "https://x.dev/"
