import json

import pytest

from analyzer.validate import (
    github_repo_from,
    has_when,
    marketplace_name_issue,
    mcp_servers,
    parse_tools,
    plugin_name_issue,
    validate_agent,
    validate_command,
    validate_hooks,
    validate_marketplace,
    validate_plugin_manifest,
    validate_skill,
)


def skill_text(
    name: str = "pdf-tools", description: str = "Fills PDF forms. Use when the user shares a PDF."
) -> str:
    return (
        f"---\nname: {name}\ndescription: {description}\n"
        "allowed-tools: Read Bash(git diff:*)\n---\n# Body\n"
    )


def test_valid_skill() -> None:
    artifact = validate_skill("skills/pdf-tools/SKILL.md", skill_text())
    assert artifact.valid and artifact.issues == []
    assert artifact.has_when
    assert artifact.tools == ["Read", "Bash(git diff:*)"]


@pytest.mark.parametrize(
    ("name", "issue"),
    [
        ("PDF-Tools", "name-format"),
        ("-pdf", "name-format"),
        ("pdf--tools", "name-format"),
        ("x" * 65, "name-too-long"),
        ("other", "name-dir-mismatch"),
    ],
)
def test_skill_name_rules(name: str, issue: str) -> None:
    artifact = validate_skill("skills/pdf-tools/SKILL.md", skill_text(name=name))
    assert issue in artifact.issues
    assert not artifact.valid


def test_skill_description_rules_and_length() -> None:
    long_desc = validate_skill("a/SKILL.md", skill_text(name="a", description="x" * 1025))
    assert "description-too-long" in long_desc.issues
    missing = validate_skill("a/SKILL.md", "---\nname: a\n---\nbody\n")
    assert "description-missing" in missing.issues
    long_body = validate_skill("a/SKILL.md", skill_text(name="a") + "line\n" * 600)
    assert "skill-over-500-lines" in long_body.issues
    assert long_body.valid  # length is a quality note, not a format error


def test_skill_without_frontmatter_still_loads_in_claude_code() -> None:
    artifact = validate_skill("x/SKILL.md", "# Only a heading\n")
    assert artifact.issues == ["no-frontmatter"]
    assert artifact.loads_in_claude_code
    assert (
        validate_skill("synced/SKILL.md", skill_text(name="synced")).loads_in_claude_code is False
    )


def test_when_detection_spanish_and_english() -> None:
    assert has_when("Úsala cuando escribas documentación")
    assert has_when("Use this skill whenever you open a PR")
    assert not has_when("Makes everything faster. Use always.")


def test_parse_tools_from_list_and_string() -> None:
    assert parse_tools(["Read", "Edit"]) == ["Read", "Edit"]
    assert parse_tools("Read, Grep Bash(npm test:*)") == ["Read", "Grep", "Bash(npm test:*)"]
    assert parse_tools(None) == []


def test_plugin_manifest_rules() -> None:
    ok = validate_plugin_manifest(
        ".claude-plugin/plugin.json", json.dumps({"name": "deploy-tools"})
    )
    assert ok.artifact.valid and ok.artifact.issues == []
    reserved = validate_plugin_manifest("p.json", json.dumps({"name": "claude-helper"}))
    assert "name-reserved" in reserved.artifact.issues and reserved.artifact.valid
    bad = validate_plugin_manifest("p.json", json.dumps({"name": "a b"}))
    assert not bad.artifact.valid
    path = validate_plugin_manifest(
        "p.json", json.dumps({"name": "a", "commands": "commands/x.md"})
    )
    assert "path-invalid: commands" in path.artifact.issues and not path.artifact.valid
    traversal = validate_plugin_manifest(
        "p.json", json.dumps({"name": "a", "agents": ["./../x.md"]})
    )
    assert not traversal.artifact.valid
    homepage = validate_plugin_manifest(
        "p.json", json.dumps({"name": "a", "homepage": "not a url"})
    )
    assert "homepage-invalid" in homepage.artifact.issues
    assert not validate_plugin_manifest("p.json", "{oops").artifact.valid
    assert validate_plugin_manifest(
        "p.json", json.dumps({"name": "a", "skills": "."})
    ).artifact.valid


def test_reserved_names() -> None:
    assert plugin_name_issue("anthropic-tools") == "name-reserved"
    assert plugin_name_issue("official-claude-kit") == "name-reserved"
    assert plugin_name_issue("my-tools") is None
    assert marketplace_name_issue("claude-plugins-official", "someone") == "name-reserved"
    assert marketplace_name_issue("claude-plugins-official", "anthropics") is None
    assert marketplace_name_issue("claudeai-x", "a") == "name-reserved"
    assert marketplace_name_issue("plugins-ñ", "a") == "name-reserved"
    assert marketplace_name_issue("acme-tools", "a") is None


def test_marketplace_validation() -> None:
    data = {
        "name": "acme",
        "owner": {"name": "Acme"},
        "plugins": [
            {"name": "local", "source": "./plugins/local"},
            {"name": "remote", "source": {"source": "github", "repo": "acme/remote"}},
            {"name": "pinned", "source": {"source": "github", "repo": "acme/p", "sha": "a" * 40}},
            {
                "name": "sub",
                "source": {
                    "source": "git-subdir",
                    "url": "https://github.com/acme/mono.git",
                    "path": "x",
                },
            },
            {"name": "broken", "source": {"source": "github"}},
            {"name": "escape", "source": "./../outside"},
            {"name": "remote", "source": "./dup"},
        ],
    }
    result = validate_marketplace(".claude-plugin/marketplace.json", json.dumps(data), "acme")
    assert result.artifact.valid and result.installable
    assert [e.name for e in result.entries] == ["local", "remote", "pinned", "sub"]
    assert result.entries[1].repo == "acme/remote" and not result.entries[1].pinned
    assert result.entries[2].pinned
    assert result.entries[3].repo == "acme/mono"
    issues = " ".join(result.artifact.issues)
    assert "entry-source-invalid: 4" in issues
    assert "entry-path-traversal: 5" in issues
    assert "duplicate-plugin: remote" in issues


def test_marketplace_missing_owner_and_reserved() -> None:
    no_owner = validate_marketplace("m.json", json.dumps({"name": "x", "plugins": []}), "o")
    assert not no_owner.artifact.valid and not no_owner.installable
    reserved = validate_marketplace(
        "m.json",
        json.dumps(
            {
                "name": "agent-skills",
                "owner": {"name": "o"},
                "plugins": [{"name": "a", "source": "./"}],
            }
        ),
        "someone",
    )
    assert reserved.artifact.valid and not reserved.installable


def test_github_repo_from() -> None:
    assert github_repo_from("acme/tool") == "acme/tool"
    assert github_repo_from("https://github.com/acme/tool.git") == "acme/tool"
    assert github_repo_from("git@github.com:acme/tool.git") == "acme/tool"
    assert github_repo_from("https://gitlab.com/a/b") is None


def test_agent_and_command() -> None:
    agent = validate_agent(
        "agents/r.md",
        "---\nname: r\ndescription: Reviews code. Use when asked.\ntools: Read, Bash\n"
        "permissionMode: bypassPermissions\n---\n",
    )
    assert agent.valid and agent.has_when
    assert "bypassPermissions" in agent.tools and "Bash" in agent.tools
    assert not validate_agent("agents/x.md", "no frontmatter").valid
    assert "name-format" in validate_agent("a.md", "---\nname: a:b\ndescription: d\n---\n").issues
    command = validate_command("commands/deploy.md", "---\ndescription: Deploy\n---\nDo it")
    assert command.valid and command.name == "deploy"
    assert "description-missing" in validate_command("commands/x.md", "Just text").issues


def test_hooks_and_mcp() -> None:
    hooks = {
        "hooks": {
            "PreToolUse": [
                {
                    "hooks": [
                        {"type": "command", "command": "./a.sh"},
                        {"type": "command", "command": "node", "args": ["x.js"]},
                    ]
                }
            ]
        }
    }
    artifact, commands = validate_hooks("hooks/hooks.json", json.dumps(hooks))
    assert artifact.valid
    assert "./a.sh" in commands and "x.js" in commands
    bare, _ = validate_hooks("hooks/hooks.json", json.dumps({"PreToolUse": []}))
    assert "hooks-wrapper-missing" in bare.issues
    artifact, servers = mcp_servers(
        ".mcp.json", json.dumps({"mcpServers": {"s": {"command": "npx", "args": ["-y", "x"]}}})
    )
    assert artifact.valid and servers == [{"name": "s", "command": "npx", "args": ["-y", "x"]}]
    broken, _ = mcp_servers(".mcp.json", "[")
    assert not broken.valid
