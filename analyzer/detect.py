"""Find the ecosystem artifacts in a repository file tree.

The rules follow the official layouts: ``SKILL.md`` per skill folder (docs #1, #2),
``.claude-plugin/plugin.json`` and ``.claude-plugin/marketplace.json`` (#3, #4), ``commands/``,
``agents/``, ``hooks/hooks.json``, ``.mcp.json`` and ``bin/`` (#3, #11).
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field

from pipeline.models import TreeEntry

EXCLUDED_DIRS = frozenset(
    {
        "node_modules",
        "vendor",
        "dist",
        "build",
        ".venv",
        "venv",
        "site-packages",
        ".git",
        "__pycache__",
        "target",
        ".next",
        "third_party",
    }
)
SCRIPT_EXTENSIONS = frozenset(
    {".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".cjs", ".ts", ".ps1", ".rb", ".pl"}
)
README_NAMES = ("README.md", "readme.md", "Readme.md", "README.MD", "README.markdown", "README")
PLUGIN_DIR = ".claude-plugin"
MARKETPLACE_PATH = f"{PLUGIN_DIR}/marketplace.json"

MAX_FILE_BYTES = 64_000
MAX_README_BYTES = 200_000
MAX_MARKETPLACE_BYTES = 512_000
MAX_TOTAL_BYTES = 1_500_000

_COMMAND_RE = re.compile(r"(^|/)commands/[^/]+\.md$")
_AGENT_RE = re.compile(r"(^|/)agents/[^/]+\.md$")
_PROJECT_CMD_RE = re.compile(r"(^|/)\.claude/commands/.+\.md$")
_PROJECT_AGENT_RE = re.compile(r"(^|/)\.claude/agents/.+\.md$")
_TEST_FILE_RE = re.compile(r"(\.test\.|_test\.|\.spec\.)[a-z]+$")


@dataclass(slots=True)
class Layout:
    readme: str | None = None
    skills: list[str] = field(default_factory=list)
    plugin_manifests: list[str] = field(default_factory=list)
    marketplace: str | None = None
    other_marketplaces: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)
    settings: list[str] = field(default_factory=list)
    mcp: list[str] = field(default_factory=list)
    scripts: list[str] = field(default_factory=list)
    bins: list[str] = field(default_factory=list)
    package_json: str | None = None
    pyproject: str | None = None
    has_tests: bool = False
    has_ci: bool = False
    has_examples: bool = False
    support_dirs: set[str] = field(default_factory=set)

    @property
    def skill_dirs(self) -> list[str]:
        return [posixpath.dirname(p) for p in self.skills]

    def has_artifacts(self) -> bool:
        return bool(
            self.skills
            or self.plugin_manifests
            or self.marketplace
            or self.commands
            or self.agents
            or self.hooks
            or self.mcp
        )


def _excluded(path: str) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.split("/")[:-1])


def _depth(path: str) -> int:
    return path.count("/")


def layout(entries: list[TreeEntry]) -> Layout:
    out = Layout()
    paths = sorted((e.path for e in entries if not _excluded(e.path)), key=lambda p: (_depth(p), p))
    readmes = {p for p in paths if "/" not in p and p in README_NAMES}
    for name in README_NAMES:
        if name in readmes:
            out.readme = name
            break
    for path in paths:
        base = posixpath.basename(path)
        parts = path.split("/")
        if base == "SKILL.md":
            out.skills.append(path)
        elif path == MARKETPLACE_PATH:
            out.marketplace = path
        elif path.endswith(f"{PLUGIN_DIR}/marketplace.json"):
            out.other_marketplaces.append(path)
        elif path.endswith(f"{PLUGIN_DIR}/plugin.json"):
            out.plugin_manifests.append(path)
        elif path.endswith("hooks/hooks.json"):
            out.hooks.append(path)
        elif path.endswith(".claude/settings.json"):
            out.settings.append(path)
        elif base == ".mcp.json":
            out.mcp.append(path)
        elif _PROJECT_CMD_RE.search(path) or _COMMAND_RE.search(path):
            out.commands.append(path)
        elif _PROJECT_AGENT_RE.search(path) or _AGENT_RE.search(path):
            out.agents.append(path)
        elif path == "package.json":
            out.package_json = path
        elif path == "pyproject.toml":
            out.pyproject = path
        if path.startswith(".github/workflows/") and base.endswith((".yml", ".yaml")):
            out.has_ci = True
        if any(
            p in {"test", "tests", "__tests__", "spec", "evals"} for p in parts[:-1]
        ) or _TEST_FILE_RE.search(base):
            out.has_tests = True
        if any(p in {"examples", "example"} for p in parts[:-1]):
            out.has_examples = True
    _collect_scripts(out, paths)
    return out


def _skill_owner(path: str, skill_dirs: list[str]) -> str | None:
    """Deepest skill folder that contains ``path`` ("" is a skill at the repo root)."""
    for directory in skill_dirs:
        if directory and path.startswith(directory + "/"):
            return directory
    return "" if "" in skill_dirs else None


def _collect_scripts(out: Layout, paths: list[str]) -> None:
    skill_dirs = sorted(set(out.skill_dirs), key=len, reverse=True)
    bin_roots = {posixpath.dirname(posixpath.dirname(p)) for p in out.plugin_manifests} | {""}
    for path in paths:
        parts = path.split("/")
        dirs, base = parts[:-1], parts[-1]
        ext = posixpath.splitext(base)[1].lower()
        owner = _skill_owner(path, skill_dirs)
        if owner is not None and base != "SKILL.md":
            rel = path[len(owner) + 1 :].split("/") if owner else parts
            if len(rel) > 1 and rel[0] in {"references", "scripts", "assets"}:
                out.support_dirs.add(rel[0])
            elif owner and len(rel) == 1 and base.endswith(".md"):
                out.support_dirs.add("docs")
        is_bin = (
            bool(dirs)
            and dirs[-1] == "bin"
            and posixpath.dirname(posixpath.dirname(path)) in bin_roots
        )
        if is_bin:
            out.bins.append(path)
        in_skill_folder = bool(owner) or (owner == "" and bool(dirs) and dirs[0] == "scripts")
        if (ext in SCRIPT_EXTENSIONS or is_bin) and (
            in_skill_folder or is_bin or "hooks" in dirs or "scripts" in dirs
        ):
            out.scripts.append(path)


def select_files(lay: Layout, sizes: dict[str, int]) -> list[str]:
    """Pick the files the analyzer needs, within count and byte caps."""
    chosen: list[str] = []
    total = 0

    def take(paths: list[str], limit: int, max_bytes: int = MAX_FILE_BYTES) -> None:
        nonlocal total
        count = 0
        for path in paths:
            if count >= limit:
                return
            size = sizes.get(path, 0)
            if size > max_bytes or total + size > MAX_TOTAL_BYTES or path in chosen:
                continue
            chosen.append(path)
            total += size
            count += 1

    if lay.readme:
        take([lay.readme], 1, MAX_README_BYTES)
    if lay.marketplace:
        take([lay.marketplace], 1, MAX_MARKETPLACE_BYTES)
    take(lay.skills, 30)
    take(lay.plugin_manifests, 20)
    take(lay.other_marketplaces, 3, MAX_MARKETPLACE_BYTES)
    take(lay.hooks, 10)
    take(lay.settings, 3)
    take(lay.mcp, 10)
    take(lay.commands, 15)
    take(lay.agents, 15)
    take(lay.scripts, 10)
    take([p for p in (lay.package_json, lay.pyproject) if p], 2)
    return chosen
