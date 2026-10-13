"""Supply-chain rules for the GitHub Actions workflows (OWASP A03:2025, investigación #29)."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parents[2] / ".github" / "workflows").glob("*.yml"))
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def _load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    # PyYAML reads the bare key `on` as the boolean True (YAML 1.1).
    if True in data:
        data["on"] = data.pop(True)
    return data


def _steps(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for job in data["jobs"].values() for step in job.get("steps", [])]


def test_the_three_workflows_exist() -> None:
    assert {p.name for p in WORKFLOWS} >= {"build.yml", "keepalive.yml", "ci.yml"}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_actions_are_pinned_to_a_full_commit_sha(path: Path) -> None:
    for step in _steps(_load(path)):
        if "uses" in step:
            assert PINNED.match(step["uses"]), f"{path.name}: {step['uses']} is not pinned"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_permissions_are_read_only_by_default(path: Path) -> None:
    data = _load(path)
    assert data["permissions"] == {"contents": "read"}
    for name, job in data["jobs"].items():
        assert "timeout-minutes" in job, f"{path.name}:{name} has no timeout"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_untrusted_event_text_is_interpolated_into_shell(path: Path) -> None:
    risky = re.compile(
        r"\$\{\{\s*github\.(event\.(issue|pull_request|comment|head_commit)|head_ref)"
    )
    for step in _steps(_load(path)):
        assert not risky.search(str(step.get("run", ""))), f"{path.name}: script injection risk"


def test_build_finishes_within_ten_minutes_and_deploys_with_minimal_rights() -> None:
    data = _load(next(p for p in WORKFLOWS if p.name == "build.yml"))
    build, deploy = data["jobs"]["build"], data["jobs"]["deploy"]
    assert build["timeout-minutes"] <= 10
    assert build["permissions"] == {"contents": "read", "pages": "read"}
    assert deploy["permissions"] == {"pages": "write", "id-token": "write"}
    assert data["concurrency"]["cancel-in-progress"] is False
    crons = [entry["cron"] for entry in data["on"]["schedule"]]
    assert crons and all(not c.startswith("0 ") for c in crons)  # never at the top of the hour
