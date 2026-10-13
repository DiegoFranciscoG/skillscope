"""Analyzer over the whole sample catalog: types, risks, installs, collections and copying."""

from functools import cache

import pytest

from analyzer.analyze import AnalysisSet, analyze_all
from analyzer.copyguard import longest_common_run
from analyzer.model import RepoAnalysis
from pipeline.models import RepoSnapshot
from pipeline.sample_api import load_sample_repos
from tests.support import NOW, SAMPLES


@cache
def analysis() -> AnalysisSet:
    snapshots = [RepoSnapshot.from_dict(r) for r in load_sample_repos(SAMPLES, NOW)]
    return analyze_all(snapshots, NOW)


def by_id(repo_id: str) -> RepoAnalysis:
    return next(a for a in analysis().analyses if a.id == repo_id)


@pytest.mark.parametrize(
    ("repo_id", "repo_type", "category"),
    [
        ("demo_nimbus-labs/pr-review-kit", "marketplace", "code_review"),
        ("demo_andes-devtools/test-pilot", "marketplace", "testing"),
        ("demo_secureflow/secret-sentinel", "marketplace", "security"),
        ("demo_acme-agents/sql-explainer", "skill", "data"),
        ("demo_quillworks/doc-scribe", "plugin", "docs_writing"),
        ("demo_pixel-forge/figma-tokens-mcp", "mcp_server", "design_ux"),
        ("demo_nimbus-labs/jira-bridge", "mcp_server", "integrations"),
        ("demo_lumen-research/lit-review-agent", "agent", "research"),
        ("demo_acme-agents/standup-notes", "command", "productivity"),
        ("demo_opsbridge/slack-notify-hook", "hook", "integrations"),
        ("demo_awesome-agentic/awesome-skill-index", "awesome_list", None),
        ("demo_templateforge/skill-starter", "template", None),
        ("demo_studybuddy-org/flashcards-coach", "skill", "education"),
        ("demo_ledgerline/invoice-checker", "skill", "finance_legal"),
        ("demo_pixel-forge/ui-critic", "skill", "design_ux"),
        ("demo_harborai/prompt-lab", "skill", "ai_ml"),
        ("demo_opsbridge/terraform-guard", "plugin", "devops"),
    ],
)
def test_types_and_categories(repo_id: str, repo_type: str, category: str | None) -> None:
    result = by_id(repo_id)
    assert result.type == repo_type
    if category:
        assert result.category == category


def test_risky_and_safe_samples() -> None:
    risky = by_id("demo_shadowtools/super-agent-pack")
    assert risky.risk_penalty == 25
    assert {"prompt-injection", "downloads-binary", "obfuscated-code"} <= {
        f.id for f in risky.risks
    }
    hook = by_id("demo_opsbridge/slack-notify-hook")
    assert {"exec-unexplained", "network-exfil", "no-license"} == {f.id for f in hook.risks}
    safe = by_id("demo_secureflow/secret-sentinel")
    assert [f.id for f in safe.risks] == ["exec-declared"]
    assert by_id("demo_acme-agents/inbox-zero").risks[0].id == "requests-credentials"


def test_validation_findings() -> None:
    broken = by_id("demo_acme-agents/broken-skill")
    issues = {i for a in broken.artifacts for i in a.issues}
    assert {"name-format", "description-missing", "no-frontmatter"} <= issues
    odd = by_id("demo_yaml-bomb/odd-skill")
    assert any("aliases" in i for a in odd.artifacts for i in a.issues)
    long_skill = by_id("demo_legacy-labs/old-linter-skill")
    assert "skill-over-500-lines" in long_skill.artifacts[0].issues


def test_installs() -> None:
    assert by_id("demo_nimbus-labs/pr-review-kit").install.one_liner == (
        "claude plugin marketplace add demo_nimbus-labs/pr-review-kit && "
        "claude plugin install pr-review-kit@nimbus-review"
    )
    # A plugin without its own marketplace is installed through the marketplace that lists it.
    doc = by_id("demo_quillworks/doc-scribe").install
    assert doc.kind == "marketplace" and "demo_nimbus-labs/agent-marketplace" in (
        doc.one_liner or ""
    )
    assert by_id("demo_quillworks/changelog-weaver").install.kind == "plugin_dir"
    assert by_id("demo_awesome-agentic/awesome-skill-index").install.kind == "list"


def test_collections_and_cooccurrence() -> None:
    result = analysis()
    assert set(result.collections["demo_quillworks/doc-scribe"]) == {
        "demo_awesome-agentic/awesome-skill-index",
        "demo_curated-hub/awesome-plugin-picks",
        "demo_nimbus-labs/agent-marketplace",
    }
    co = result.co_occurrence["demo_nimbus-labs/pr-review-kit"]
    assert co["demo_andes-devtools/test-pilot"] == 2  # both lists contain both
    assert "unknown-owner/not-in-index" not in result.collections


def test_analysis_roundtrip_through_cache() -> None:
    for item in analysis().analyses:
        restored = RepoAnalysis.from_dict(item.meta, item.to_dict())
        assert restored.to_dict() == item.to_dict()
        assert restored.summary(NOW) == item.summary(NOW)


def test_languages() -> None:
    assert by_id("demo_quillworks/guia-estilo-es").readme_lang == "es"
    assert by_id("demo_zhihui-tools/translate-cn").readme_lang == "zh"
    assert by_id("demo_nimbus-labs/pr-review-kit").readme_lang == "en"


def test_acceptance_no_third_party_text_is_copied() -> None:
    """Fails if any generated text shares more than 15 consecutive words with the original."""
    for item in analysis().analyses:
        for text in [item.summary(NOW), item.what(NOW), *item.when]:
            assert longest_common_run(text, item.source_text) <= 15, (item.id, text)


def test_summaries_never_contain_emails() -> None:
    for item in analysis().analyses:
        assert "@example.com" not in " ".join([item.summary(NOW), item.what(NOW), *item.when])
