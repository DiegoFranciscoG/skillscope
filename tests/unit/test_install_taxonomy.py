import json

from analyzer.install import build_install, copy_install, marketplace_install, mcp_install
from analyzer.language import detect
from analyzer.model import Artifact
from analyzer.taxonomy import (
    classify_category,
    classify_cause,
    determine_type,
    github_links,
    is_mcp_package,
)


def _type(**flags: object) -> str:
    base = {
        "is_template": False,
        "has_marketplace": False,
        "has_plugin": False,
        "has_skills": False,
        "is_mcp": False,
        "has_agents": False,
        "has_commands": False,
        "has_hooks": False,
        "looks_awesome": False,
        "link_count": 0,
    }
    base.update(flags)
    return determine_type(**base)  # type: ignore[arg-type]


def test_type_precedence() -> None:
    assert _type(is_template=True, has_marketplace=True) == "template"
    assert _type(has_marketplace=True, has_plugin=True, has_skills=True) == "marketplace"
    assert _type(looks_awesome=True, link_count=12, has_skills=True) == "awesome_list"
    assert _type(has_plugin=True, has_skills=True) == "plugin"
    assert _type(has_skills=True, is_mcp=True) == "skill"
    assert _type(is_mcp=True, has_agents=True) == "mcp_server"
    assert _type(has_agents=True, has_commands=True) == "agent"
    assert _type(has_commands=True, has_hooks=True) == "command"
    assert _type(has_hooks=True) == "hook"
    assert _type(link_count=10) == "awesome_list"
    assert _type() == "skill"


def test_category_and_cause() -> None:
    review = classify_category([("pr review kit", 3), ("Reviews the diff of a pull request", 1)])
    assert review.primary == "code_review"
    assert "review" in review.terms
    tests = classify_category([("Escribe pruebas unitarias y e2e con playwright", 1)])
    assert tests.primary == "testing"
    assert classify_category([("nothing relevant here", 1)]).primary == "development"
    assert classify_cause([("conventional commits style guide", 1)]).primary == "standardize"
    assert classify_cause([("OWASP audit checklist for compliance", 1)]).primary == "comply"
    assert classify_cause([("", 1)]).primary == "automate"


def test_secondary_categories_need_half_the_score() -> None:
    result = classify_category([("security review of pull requests and secrets", 1)])
    assert result.primary in {"security", "code_review"}
    assert result.secondary


def test_mcp_package_detection() -> None:
    assert is_mcp_package('{"dependencies": {"@modelcontextprotocol/sdk": "1.0.0"}}', None)
    assert is_mcp_package(None, 'dependencies = ["mcp==1.18.0"]')
    assert is_mcp_package(None, 'dependencies = ["fastmcp>=2"]')
    assert not is_mcp_package('{"dependencies": {"react": "19"}}', 'dependencies = ["mcpx"]')


def test_github_links() -> None:
    text = (
        "[a](https://github.com/acme/tool) https://github.com/acme/tool.git "
        "https://github.com/topics/x https://github.com/me/self https://github.com/b/c."
    )
    assert github_links(text, exclude="me/self") == ["acme/tool", "b/c"]


def test_language_detection() -> None:
    assert detect("The tool reads the file and writes the result to your folder for you.") == "en"
    assert (
        detect("La herramienta lee el archivo y escribe el resultado en la carpeta de los datos.")
        == "es"
    )
    assert detect("这个技能可以把技术文档在中文和英文之间翻译并保留代码块和术语") == "zh"
    assert detect("") == "und"
    assert detect("```\ncode only\n```") == "und"


def test_marketplace_install_commands() -> None:
    install = marketplace_install("acme/tools", "acme", ["fmt", "lint"])
    assert install is not None
    assert install.steps[0].command == "/plugin marketplace add acme/tools"
    assert install.steps[1].command == "/plugin install fmt@acme"
    assert (
        install.one_liner
        == "claude plugin marketplace add acme/tools && claude plugin install fmt@acme"
    )
    assert "2 plugins" in install.note
    assert marketplace_install("acme/tools", "bad name", ["x"]) is None
    assert marketplace_install("acme/tools", "acme", ["$(rm -rf)"]) is None


def test_copy_install_variants() -> None:
    nested = copy_install("acme/skills", "skills/pdf/SKILL.md", "skills", "skill")
    assert nested is not None and nested.one_liner is not None
    assert "cp -r /tmp/skillscope-skills/skills/pdf ~/.claude/skills/pdf" in nested.one_liner
    root = copy_install("acme/pdf-skill", "SKILL.md", "skills", "skill")
    assert root is not None
    assert (
        root.one_liner
        == "git clone --depth 1 https://github.com/acme/pdf-skill.git ~/.claude/skills/pdf-skill"
    )
    agent = copy_install("acme/a", ".claude/agents/r.md", "agents", "agent")
    assert agent is not None and "~/.claude/agents/" in (agent.one_liner or "")
    assert copy_install("acme/a", "we ird/x.md", "agents", "agent") is None


def test_mcp_install() -> None:
    npm = mcp_install("acme/db-mcp", json.dumps({"name": "@acme/db-mcp", "version": "1.2.3"}), None)
    assert npm.one_liner == "claude mcp add db-mcp -- npx -y @acme/db-mcp@1.2.3"
    py = mcp_install("acme/x", None, '[project]\nname = "x-mcp"\nversion = "0.1.0"\n')
    assert py.one_liner == "claude mcp add x -- uvx x-mcp==0.1.0"
    private = mcp_install(
        "acme/x", json.dumps({"name": "x", "version": "1.0.0", "private": True}), None
    )
    assert private.kind == "manual"


def test_build_install_by_type() -> None:
    common = {
        "repo_id": "acme/r",
        "marketplace_name": None,
        "marketplace_installable": False,
        "marketplace_plugins": [],
        "artifacts": [Artifact("skill", "s/SKILL.md", "s", True)],
        "package_json": None,
        "pyproject": None,
    }
    assert build_install(repo_type="awesome_list", **common).kind == "list"  # type: ignore[arg-type]
    assert build_install(repo_type="template", **common).kind == "template"  # type: ignore[arg-type]
    assert build_install(repo_type="plugin", **common).kind == "plugin_dir"  # type: ignore[arg-type]
    assert build_install(repo_type="skill", **common).kind == "skill_copy"  # type: ignore[arg-type]
    hook = common | {"artifacts": []}
    assert build_install(repo_type="hook", **hook).kind == "manual"  # type: ignore[arg-type]
    reserved = common | {"marketplace_name": "agent-skills"}
    assert build_install(repo_type="marketplace", **reserved).kind == "manual"  # type: ignore[arg-type]
