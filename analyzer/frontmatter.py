"""Safe YAML frontmatter parsing for SKILL.md, agents and commands.

Third-party YAML is untrusted input. ``yaml.safe_load`` never builds arbitrary objects, and
on top of that anchors/aliases are rejected (they enable "billion laughs" memory bombs) and
the block is capped at 16 KB (docs/modelo-datos.md R2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml

MAX_FRONTMATTER = 16_000


@dataclass(slots=True)
class Frontmatter:
    present: bool
    fields: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    body: str = ""
    body_line: int = 1


def _has_aliases(raw: str) -> bool:
    for event in yaml.parse(raw, Loader=yaml.SafeLoader):
        if isinstance(event, yaml.AliasEvent):
            return True
        anchor = getattr(event, "anchor", None)
        if anchor is not None:
            return True
    return False


def parse(text: str) -> Frontmatter:
    """Frontmatter is only read when ``---`` is the very first line (docs #1)."""
    text = text.removeprefix("﻿")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return Frontmatter(present=False, body=text)
    end = None
    size = 0
    for index in range(1, len(lines)):
        size += len(lines[index]) + 1
        if size > MAX_FRONTMATTER:
            return Frontmatter(present=True, error="frontmatter too large", body=text)
        if lines[index].strip() in {"---", "..."}:
            end = index
            break
    if end is None:
        return Frontmatter(present=True, error="frontmatter not closed", body=text)
    raw = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1 :])
    try:
        if _has_aliases(raw):
            return Frontmatter(present=True, error="anchors/aliases not allowed", body=body)
        data = yaml.safe_load(raw) if raw.strip() else {}
    except yaml.YAMLError as exc:
        reason = str(exc).splitlines()[0][:120]
        return Frontmatter(
            present=True, error=f"invalid yaml: {reason}", body=body, body_line=end + 2
        )
    if not isinstance(data, dict):
        return Frontmatter(present=True, error="frontmatter is not a mapping", body=body)
    fields = {str(k): v for k, v in data.items()}
    return Frontmatter(present=True, fields=fields, body=body, body_line=end + 2)
