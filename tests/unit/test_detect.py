from analyzer.detect import MAX_FILE_BYTES, layout, select_files
from pipeline.models import TreeEntry


def _tree(*paths: str, size: int = 100) -> list[TreeEntry]:
    return [TreeEntry(p, size) for p in paths]


def test_plugin_layout_is_detected() -> None:
    lay = layout(
        _tree(
            "README.md",
            ".claude-plugin/plugin.json",
            ".claude-plugin/marketplace.json",
            "skills/review/SKILL.md",
            "skills/review/references/check.md",
            "skills/review/scripts/run.sh",
            "commands/deploy.md",
            "agents/reviewer.md",
            "hooks/hooks.json",
            "hooks/format.sh",
            ".mcp.json",
            "bin/tool",
            "node_modules/x/SKILL.md",
            ".github/workflows/ci.yml",
            "tests/test_x.py",
            "examples/demo.md",
        )
    )
    assert lay.readme == "README.md"
    assert lay.marketplace == ".claude-plugin/marketplace.json"
    assert lay.plugin_manifests == [".claude-plugin/plugin.json"]
    assert lay.skills == ["skills/review/SKILL.md"]  # node_modules ignored
    assert lay.commands == ["commands/deploy.md"]
    assert lay.agents == ["agents/reviewer.md"]
    assert lay.hooks == ["hooks/hooks.json"]
    assert lay.mcp == [".mcp.json"]
    assert "bin/tool" in lay.bins
    assert {"skills/review/scripts/run.sh", "hooks/format.sh", "bin/tool"} <= set(lay.scripts)
    assert lay.support_dirs == {"references", "scripts"}
    assert lay.has_ci and lay.has_tests and lay.has_examples
    assert lay.has_artifacts()


def test_project_level_commands_and_agents() -> None:
    lay = layout(_tree(".claude/commands/standup.md", ".claude/agents/x/reviewer.md"))
    assert lay.commands == [".claude/commands/standup.md"]
    assert lay.agents == [".claude/agents/x/reviewer.md"]


def test_root_skill_and_nested_marketplace() -> None:
    lay = layout(_tree("SKILL.md", "scripts/a.py", "plugins/p/.claude-plugin/marketplace.json"))
    assert lay.skills == ["SKILL.md"]
    assert lay.marketplace is None
    assert lay.other_marketplaces == ["plugins/p/.claude-plugin/marketplace.json"]
    assert "scripts/a.py" in lay.scripts


def test_repo_without_artifacts() -> None:
    lay = layout(_tree("README.md", "src/app.py", "docs/guide.md"))
    assert not lay.has_artifacts()


def test_select_files_respects_caps() -> None:
    entries = _tree("README.md", *[f"s{i}/SKILL.md" for i in range(40)])
    entries.append(TreeEntry("big/SKILL.md", MAX_FILE_BYTES + 1))
    lay = layout(entries)
    sizes = {e.path: e.size for e in entries}
    chosen = select_files(lay, sizes)
    assert chosen[0] == "README.md"
    assert len([p for p in chosen if p.endswith("SKILL.md")]) == 30
    assert "big/SKILL.md" not in chosen
