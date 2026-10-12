from pathlib import Path

import pytest

from pipeline.config import ConfigError, load_settings, normalize_site_url


def test_online_mode_fails_fast_without_token() -> None:
    with pytest.raises(ConfigError, match="GITHUB_TOKEN"):
        load_settings({"SKILLSCOPE_SITE_URL": "https://x.github.io/s/"}, offline=False, root=Path())


def test_online_mode_fails_fast_without_site_url() -> None:
    with pytest.raises(ConfigError, match="SKILLSCOPE_SITE_URL"):
        load_settings({"GITHUB_TOKEN": "t"}, offline=False, root=Path())


def test_offline_mode_needs_no_secrets() -> None:
    settings = load_settings({}, offline=True, root=Path("/repo"))
    assert settings.github_token is None
    assert settings.site_url == "http://localhost:8080/"
    assert settings.state_dir == Path("/repo/data/state")


def test_token_never_appears_in_repr() -> None:
    settings = load_settings(
        {"GITHUB_TOKEN": "ghp_should_not_leak", "SKILLSCOPE_SITE_URL": "https://a.b/c"},
        offline=False,
        root=Path(),
    )
    assert "ghp_should_not_leak" not in repr(settings)
    assert settings.site_url == "https://a.b/c/"


def test_budgets_are_validated() -> None:
    with pytest.raises(ConfigError, match="entero"):
        load_settings({"SKILLSCOPE_BUDGET_REST": "many"}, offline=True, root=Path())
    with pytest.raises(ConfigError, match="entre"):
        load_settings({"SKILLSCOPE_BUDGET_SEARCH": "999"}, offline=True, root=Path())
    settings = load_settings({"SKILLSCOPE_BUDGET_REST": "700"}, offline=True, root=Path())
    assert settings.budgets.rest == 700


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
