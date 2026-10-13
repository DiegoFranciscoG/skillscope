"""Removal requests: whoever owns a repository can take it out of the index, no questions asked."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

OPTOUT_TOPIC = "skillscope-optout"
OPTOUT_LABEL = "opt-out"
APPROVED_LABEL = "opt-out-approved"

# Owners: GitHub logins use letters, digits and hyphens. The underscore is accepted only so the
# fictional demo owners (demo_*) parse; GitHub never allows it, so they cannot match a real account.
_REPO_IN_TEXT = re.compile(
    r"(?:https?://github\.com/)?\b([A-Za-z0-9](?:[A-Za-z0-9_-]{0,38}))/([A-Za-z0-9._-]{1,100})\b"
)


def from_file(path: Path) -> set[str]:
    if not path.exists():
        return set()
    out: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.split("#", 1)[0].strip()
        if "/" in value:
            out.add(value.lower())
    return out


def repo_from_issue(body: str) -> str | None:
    for match in _REPO_IN_TEXT.finditer(body or ""):
        owner, name = match.group(1), match.group(2).removesuffix(".git").rstrip(".")
        if owner.lower() in {"www", "github"}:
            continue
        return f"{owner}/{name}"
    return None


def from_issues(issues: list[dict[str, Any]]) -> set[str]:
    """Accept a request automatically when the issue author owns the repo, or when approved."""
    out: set[str] = set()
    for issue in issues:
        if "pull_request" in issue:
            continue
        repo = repo_from_issue(str(issue.get("body") or ""))
        if not repo:
            continue
        author = str((issue.get("user") or {}).get("login") or "").lower()
        labels = {str(label.get("name", "")).lower() for label in issue.get("labels", [])}
        owner = repo.split("/")[0].lower()
        if author == owner or APPROVED_LABEL in labels:
            out.add(repo.lower())
    return out


def has_optout_topic(topics: list[str]) -> bool:
    return OPTOUT_TOPIC in {t.lower() for t in topics}
