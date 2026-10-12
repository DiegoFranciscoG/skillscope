"""Format validation for skills, plugin manifests, marketplaces, agents, commands and hooks.

Rules and their sources are listed in docs/modelo-datos.md (R1–R4).
"""

from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass, field
from typing import Any

from analyzer.frontmatter import parse as parse_frontmatter
from analyzer.model import Artifact, MarketplaceEntry
from analyzer.text import fold

SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
KEBAB_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
ID_PART_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
REPO_RE = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")
GITHUB_URL_RE = re.compile(r"github\.com[/:]([A-Za-z0-9-]+)/([A-Za-z0-9._-]+?)(?:\.git)?/?$")
TOOL_RE = re.compile(r"[A-Za-z_][\w.-]*(?:\([^)]*\))?")

MAX_SKILL_NAME = 64
MAX_DESCRIPTION = 1024
MAX_SKILL_LINES = 500

WHEN_RE = re.compile(
    r"\b(use (it |this |this skill |this agent |me )?(when|whenever|for|to|if|after|before|on)\b"
    r"|when (the )?(user|you|working|asked|needed|someone|a |an )"
    r"|trigger(s|ed)? (on|when)|invoke (it )?when|activate when"
    r"|usala cuando|usalo cuando|usar cuando|uselo cuando"
    r"|cuando (el usuario|necesites|trabajes|quieras|haya|escribas|prepares))"
)

RESERVED_SKILL_DIRS = frozenset({"synced", "anthropic-skills"})
RESERVED_MARKETPLACES = frozenset(
    {
        "claude-code-marketplace", "claude-code-plugins", "claude-plugins-official",
        "anthropic-marketplace", "anthropic-plugins", "agent-skills", "anthropic-agent-skills",
        "life-sciences", "knowledge-work-plugins", "claude-for-legal",
        "claude-for-financial-services", "financial-services-plugins", "first-party-plugins",
        "claude-tag-plugins", "claude-community", "claude-plugins-community", "healthcare",
        "anthropic-plugin-directory", "claude-plugin-directory", "inline", "builtin",
        "skills-dir", "synced", "claude-plugin-test", "npm", "pip", "uv", "cargo", "github", "gh",
        "constructor", "hasownproperty", "isprototypeof", "propertyisenumerable",
        "tolocalestring", "tostring", "valueof",
    }
)  # fmt: skip
RESERVED_PLUGIN_EXACT = frozenset(
    {"claude", "anthropic", "anthropics", "claude-code", "claude-mods"}
)
RESERVED_PLUGIN_PREFIXES = ("claude-", "anthropic-", "anthropics-", "cc-plugin-")
SOURCE_FIELDS = {
    "github": ("repo",),
    "url": ("url",),
    "git-subdir": ("url", "path"),
    "npm": ("package",),
    "archive": ("url",),
    "command": ("command",),
}
COMPONENT_PATH_KEYS = ("commands", "agents", "skills", "hooks", "mcpServers", "outputStyles")


def has_when(text: str) -> bool:
    return bool(WHEN_RE.search(fold(text)))


def parse_tools(value: Any) -> list[str]:
    if isinstance(value, list):
        items = [str(v) for v in value]
    elif isinstance(value, str):
        items = TOOL_RE.findall(value)
    else:
        return []
    return [i.strip() for i in items if i.strip()][:30]


def _line_count(text: str) -> int:
    return text.count("\n") + (0 if text.endswith("\n") or not text else 1)


# ---------------------------------------------------------------------------------------------
def validate_skill(path: str, text: str) -> Artifact:
    directory = posixpath.basename(posixpath.dirname(path))
    fm = parse_frontmatter(text)
    issues: list[str] = []
    name = ""
    description = ""
    tools: list[str] = []
    if not fm.present:
        issues.append("no-frontmatter")
    elif fm.error:
        issues.append(f"frontmatter-error: {fm.error}")
    else:
        raw_name = fm.fields.get("name")
        raw_desc = fm.fields.get("description")
        name = str(raw_name).strip() if raw_name is not None else ""
        description = str(raw_desc).strip() if raw_desc is not None else ""
        if not name:
            issues.append("name-missing")
        else:
            if len(name) > MAX_SKILL_NAME:
                issues.append("name-too-long")
            if not SKILL_NAME_RE.match(name):
                issues.append("name-format")
            if directory and name != directory:
                issues.append("name-dir-mismatch")
        if not description:
            issues.append("description-missing")
        elif len(description) > MAX_DESCRIPTION:
            issues.append("description-too-long")
        tools = parse_tools(fm.fields.get("allowed-tools"))
        extra_when = fm.fields.get("when_to_use")
        if isinstance(extra_when, str):
            description = f"{description} {extra_when}".strip()
    lines = _line_count(text)
    if lines > MAX_SKILL_LINES:
        issues.append("skill-over-500-lines")
    blocking = [i for i in issues if i != "skill-over-500-lines"]
    return Artifact(
        kind="skill",
        path=path,
        name=name or directory or "skill",
        valid=not blocking,
        issues=issues,
        description=description,
        lines=lines,
        tools=tools,
        has_when=bool(description) and has_when(description),
        loads_in_claude_code=directory.lower() not in RESERVED_SKILL_DIRS,
    )


def validate_agent(path: str, text: str) -> Artifact:
    fm = parse_frontmatter(text)
    issues: list[str] = []
    name = description = ""
    tools: list[str] = []
    if not fm.present:
        issues.append("no-frontmatter")
    elif fm.error:
        issues.append(f"frontmatter-error: {fm.error}")
    else:
        name = str(fm.fields.get("name") or "").strip()
        description = str(fm.fields.get("description") or "").strip()
        if not name:
            issues.append("name-missing")
        elif ":" in name or len(name) > 256:
            issues.append("name-format")
        if not description:
            issues.append("description-missing")
        tools = parse_tools(fm.fields.get("tools"))
        mode = str(fm.fields.get("permissionMode") or "")
        if mode == "bypassPermissions":
            tools.append("bypassPermissions")
    return Artifact(
        kind="agent",
        path=path,
        name=name or posixpath.splitext(posixpath.basename(path))[0],
        valid=not issues,
        issues=issues,
        description=description,
        lines=_line_count(text),
        tools=tools,
        has_when=bool(description) and has_when(description),
    )


def validate_command(path: str, text: str) -> Artifact:
    fm = parse_frontmatter(text)
    issues: list[str] = []
    description = ""
    tools: list[str] = []
    if fm.present and fm.error:
        issues.append(f"frontmatter-error: {fm.error}")
    elif fm.present:
        description = str(fm.fields.get("description") or "").strip()
        tools = parse_tools(fm.fields.get("allowed-tools"))
    if not description:
        issues.append("description-missing")
    return Artifact(
        kind="command",
        path=path,
        name=posixpath.splitext(posixpath.basename(path))[0],
        valid=not any(i.startswith("frontmatter-error") for i in issues),
        issues=issues,
        description=description,
        lines=_line_count(text),
        tools=tools,
    )


# ---------------------------------------------------------------------------------------------
def _load_json(text: str) -> tuple[Any, str | None]:
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, f"invalid-json: line {exc.lineno}"


def plugin_name_issue(name: str) -> str | None:
    lowered = name.lower()
    if lowered in RESERVED_PLUGIN_EXACT or lowered.startswith(RESERVED_PLUGIN_PREFIXES):
        return "name-reserved"
    if "official" in lowered and ("claude" in lowered or "anthropic" in lowered):
        return "name-reserved"
    return None


def _check_paths(data: dict[str, Any], issues: list[str]) -> None:
    """Component paths must start with ``./`` and stay inside the plugin (docs #3)."""
    for key in COMPONENT_PATH_KEYS:
        value = data.get(key)
        values = value if isinstance(value, list) else [value]
        for item in values:
            if not isinstance(item, str):
                continue  # inline objects are allowed
            if key == "mcpServers" and item.startswith("https://"):
                continue
            if key == "skills" and item in {".", "./"}:
                continue
            if not item.startswith("./") or ".." in item.split("/"):
                issues.append(f"path-invalid: {key}")
                return


@dataclass(slots=True)
class PluginManifest:
    artifact: Artifact
    data: dict[str, Any] = field(default_factory=dict)


def validate_plugin_manifest(path: str, text: str) -> PluginManifest:
    data, error = _load_json(text)
    issues: list[str] = []
    name = ""
    if error:
        issues.append(error)
    elif not isinstance(data, dict):
        issues.append("not-an-object")
    else:
        name = str(data.get("name") or "").strip()
        if not name:
            issues.append("name-missing")
        elif re.search(r"[\s@:/\\]", name):
            issues.append("name-invalid")
        else:
            if not KEBAB_RE.match(name):
                issues.append("name-not-kebab-case")
            reserved = plugin_name_issue(name)
            if reserved:
                issues.append(reserved)
        homepage = data.get("homepage")
        if homepage is not None and not re.match(r"^https?://\S+$", str(homepage)):
            issues.append("homepage-invalid")
        _check_paths(data, issues)
    blocking = {"invalid-json", "not-an-object", "name-missing", "name-invalid", "homepage-invalid"}
    valid = not any(i.split(":")[0] in blocking or i.startswith("path-invalid") for i in issues)
    clean = data if isinstance(data, dict) else {}
    artifact = Artifact(
        kind="plugin_manifest",
        path=path,
        name=name or posixpath.basename(posixpath.dirname(posixpath.dirname(path))) or "plugin",
        valid=valid,
        issues=issues,
        description=str(clean.get("description") or "")[:500],
    )
    return PluginManifest(artifact, clean)


def marketplace_name_issue(name: str, owner: str) -> str | None:
    lowered = name.lower()
    if owner.lower() == "anthropics":
        return None
    if lowered in RESERVED_MARKETPLACES or lowered.startswith("claudeai-"):
        return "name-reserved"
    if not name.isascii():
        return "name-reserved"
    if "official" in lowered and ("claude" in lowered or "anthropic" in lowered):
        return "name-reserved"
    return None


def github_repo_from(value: str) -> str | None:
    value = value.strip()
    if REPO_RE.match(value):
        return value
    match = GITHUB_URL_RE.search(value)
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    return None


def _entry(raw: Any, issues: list[str], index: int) -> MarketplaceEntry | None:
    if not isinstance(raw, dict):
        issues.append(f"entry-invalid: {index}")
        return None
    name = str(raw.get("name") or "").strip()
    source = raw.get("source")
    if not name or not ID_PART_RE.match(name) or source is None:
        issues.append(f"entry-invalid: {index}")
        return None
    if isinstance(source, str):
        if source in {".", "./"} or source.startswith("./"):
            if ".." in source.split("/"):
                issues.append(f"entry-path-traversal: {index}")
                return None
            return MarketplaceEntry(name, "relative", None, True)
        return MarketplaceEntry(name, "bare", None, True)
    if not isinstance(source, dict):
        issues.append(f"entry-invalid: {index}")
        return None
    kind = str(source.get("source") or "")
    required = SOURCE_FIELDS.get(kind)
    if required is None or any(not source.get(f) for f in required):
        issues.append(f"entry-source-invalid: {index}")
        return None
    repo = None
    if kind == "github":
        repo = github_repo_from(str(source["repo"]))
    elif kind in {"url", "git-subdir"}:
        repo = github_repo_from(str(source["url"]))
    pinned = bool(source.get("sha")) or (kind == "npm" and bool(source.get("version")))
    if kind == "archive":
        pinned = bool(source.get("sha256"))
    return MarketplaceEntry(name, kind, repo, pinned)


@dataclass(slots=True)
class MarketplaceManifest:
    artifact: Artifact
    name: str | None
    entries: list[MarketplaceEntry]
    installable: bool


def validate_marketplace(path: str, text: str, repo_owner: str) -> MarketplaceManifest:
    data, error = _load_json(text)
    issues: list[str] = []
    name: str | None = None
    entries: list[MarketplaceEntry] = []
    if error:
        issues.append(error)
    elif not isinstance(data, dict):
        issues.append("not-an-object")
    else:
        name = str(data.get("name") or "").strip() or None
        if not name:
            issues.append("name-missing")
        elif not ID_PART_RE.match(name) or ".." in name:
            issues.append("name-invalid")
        else:
            reserved = marketplace_name_issue(name, repo_owner)
            if reserved:
                issues.append(reserved)
        owner = data.get("owner")
        if not isinstance(owner, dict) or not str(owner.get("name") or "").strip():
            issues.append("owner-missing")
        plugins = data.get("plugins")
        if not isinstance(plugins, list):
            issues.append("plugins-missing")
        else:
            seen: set[str] = set()
            for index, raw in enumerate(plugins):
                entry = _entry(raw, issues, index)
                if entry is None:
                    continue
                if entry.name in seen:
                    issues.append(f"duplicate-plugin: {entry.name}")
                    continue
                seen.add(entry.name)
                entries.append(entry)
            if not plugins:
                issues.append("no-plugins")
    blocking = {"invalid-json", "not-an-object", "name-missing", "name-invalid", "owner-missing"}
    valid = not any(i.split(":")[0] in blocking or i == "plugins-missing" for i in issues)
    installable = valid and "name-reserved" not in issues and bool(entries)
    artifact = Artifact(
        kind="marketplace_manifest",
        path=path,
        name=name or "marketplace",
        valid=valid,
        issues=issues,
        description=str((data or {}).get("description") or "")[:500]
        if isinstance(data, dict)
        else "",
    )
    return MarketplaceManifest(artifact, name, entries, installable)


# ---------------------------------------------------------------------------------------------
def hook_commands(data: Any) -> list[str]:
    """Every ``command`` string inside a hooks document (any nesting)."""
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "command" and isinstance(node.get("command"), str):
                found.append(node["command"])
            for key, value in node.items():
                if key == "args" and isinstance(value, list) and node.get("command"):
                    found.append(" ".join(str(v) for v in value))
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return found


def validate_hooks(path: str, text: str) -> tuple[Artifact, list[str]]:
    data, error = _load_json(text)
    issues: list[str] = []
    commands: list[str] = []
    if error:
        issues.append(error)
    else:
        target = data.get("hooks") if isinstance(data, dict) else None
        if path.endswith("hooks.json") and not isinstance(target, dict):
            issues.append("hooks-wrapper-missing")
        commands = hook_commands(target if isinstance(target, dict) else data)
    artifact = Artifact(
        kind="hook_config",
        path=path,
        name=posixpath.basename(path),
        valid=not issues,
        issues=issues,
    )
    return artifact, commands


def mcp_servers(path: str, text: str) -> tuple[Artifact, list[dict[str, Any]]]:
    data, error = _load_json(text)
    issues: list[str] = []
    servers: list[dict[str, Any]] = []
    if error:
        issues.append(error)
    elif isinstance(data, dict):
        block = data.get("mcpServers", data)
        if isinstance(block, dict):
            for name, conf in block.items():
                if isinstance(conf, dict):
                    servers.append({"name": str(name), **conf})
    else:
        issues.append("not-an-object")
    artifact = Artifact(
        kind="mcp_config",
        path=path,
        name=posixpath.basename(path),
        valid=not issues,
        issues=issues,
    )
    return artifact, servers
