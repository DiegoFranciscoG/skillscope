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
# Folders whose files are tests, fixtures or documentation, never installable artifacts.
NON_ARTIFACT_DIRS = frozenset(
    {"test", "tests", "__tests__", "fixtures", "fixture", "testdata", "docs", "doc"}
)
README_NAMES = ("README.md", "readme.md", "Readme.md", "README.MD", "README.markdown", "README")
PLUGIN_DIR = ".claude-plugin"
MARKETPLACE_PATH = f"{PLUGIN_DIR}/marketplace.json"

MAX_FILE_BYTES = 64_000
MAX_README_BYTES = 200_000
MAX_MARKETPLACE_BYTES = 512_000
MAX_TOTAL_BYTES = 1_500_000

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
    scripts: list[str] = field(default_factory=list)  # fetched and scanned
    exec_scripts: list[str] = field(default_factory=list)  # can be run by the agent
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


def _non_artifact(path: str) -> bool:
    return any(part in NON_ARTIFACT_DIRS for part in path.split("/")[:-1])


def _component_root(path: str, folder: str) -> str | None:
    """Directory that holds ``<folder>/<file>.md`` ("" for the repo root).

    Only direct children count, except under ``.claude/`` where subfolders are scanned (#11).
    """
    padded = "/" + path
    marker = f"/{folder}/"
    index = padded.rfind(marker)
    if index < 0 or not path.endswith(".md"):
        return None
    root = padded[1:index] if index > 0 else ""
    rest = padded[index + len(marker) :]
    if "/" in rest and not (root == ".claude" or root.endswith("/.claude")):
        return None
    return root


def layout(entries: list[TreeEntry]) -> Layout:
    out = Layout()
    paths = sorted((e.path for e in entries if not _excluded(e.path)), key=lambda p: (_depth(p), p))
    readmes = {p for p in paths if "/" not in p and p in README_NAMES}
    for name in README_NAMES:
        if name in readmes:
            out.readme = name
            break
    # Folders that can hold plugin components: the repo root, plugin roots and the parent of
    # any "skills/" folder that contains SKILL.md files.
    roots: set[str] = {""}
    for path in paths:
        if path.endswith((f"{PLUGIN_DIR}/plugin.json", f"{PLUGIN_DIR}/marketplace.json")):
            roots.add(posixpath.dirname(posixpath.dirname(path)))
        elif path.endswith("/SKILL.md") and "/skills/" in "/" + path:
            roots.add(("/" + path).rsplit("/skills/", 1)[0][1:])

    for path in paths:
        base = posixpath.basename(path)
        parts = path.split("/")
        if path.startswith(".github/workflows/") and base.endswith((".yml", ".yaml")):
            out.has_ci = True
        if any(
            p in {"test", "tests", "__tests__", "spec", "evals"} for p in parts[:-1]
        ) or _TEST_FILE_RE.search(base):
            out.has_tests = True
        if any(p in {"examples", "example"} for p in parts[:-1]):
            out.has_examples = True
        if _non_artifact(path):
            continue
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
        elif path == "package.json":
            out.package_json = path
        elif path == "pyproject.toml":
            out.pyproject = path
        else:
            for folder, bucket in (("commands", out.commands), ("agents", out.agents)):
                root = _component_root(path, folder)
                if root is not None and (root in roots or root.endswith(".claude")):
                    bucket.append(path)
                    break
    _collect_scripts(out, paths, roots)
    return out


def _skill_owner(path: str, skill_dirs: frozenset[str]) -> str | None:
    """Deepest skill folder that contains ``path`` ("" is a skill at the repo root).

    Walks up the path's own ancestors (O(depth)) instead of testing every skill folder.
    """
    directory = posixpath.dirname(path)
    while directory:
        if directory in skill_dirs:
            return directory
        directory = posixpath.dirname(directory)
    return "" if "" in skill_dirs else None


def _collect_scripts(out: Layout, paths: list[str], roots: set[str]) -> None:
    skill_dirs = frozenset(out.skill_dirs)
    hook_dirs = {f"{r}/hooks" if r else "hooks" for r in roots} | {".claude/hooks"}
    for path in paths:
        if _non_artifact(path):
            continue
        parts = path.split("/")
        dirs, base = parts[:-1], parts[-1]
        directory = posixpath.dirname(path)
        ext = posixpath.splitext(base)[1].lower()
        owner = _skill_owner(path, skill_dirs)
        if owner is not None and base != "SKILL.md":
            rel = path[len(owner) + 1 :].split("/") if owner else parts
            if len(rel) > 1 and rel[0] in {"references", "scripts", "assets"}:
                out.support_dirs.add(rel[0])
            elif owner and len(rel) == 1 and base.endswith(".md"):
                out.support_dirs.add("docs")
        is_bin = bool(dirs) and dirs[-1] == "bin" and posixpath.dirname(directory) in roots
        if is_bin:
            out.bins.append(path)
        in_skill_folder = bool(owner) or (owner == "" and bool(dirs) and dirs[0] == "scripts")
        is_script = ext in SCRIPT_EXTENSIONS or is_bin
        if is_script and (in_skill_folder or is_bin):
            out.exec_scripts.append(path)
            out.scripts.append(path)
        elif is_script and directory in hook_dirs:
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
