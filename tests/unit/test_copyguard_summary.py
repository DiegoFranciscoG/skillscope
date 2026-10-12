from datetime import UTC, datetime

from analyzer.copyguard import longest_common_run, overlaps
from analyzer.model import Artifact
from analyzer.summary import build_summary, build_when, trigger_words

NOW = datetime(2026, 10, 12, tzinfo=UTC)


def test_longest_common_run() -> None:
    assert longest_common_run("a b c d", "x a b c y") == 3
    assert longest_common_run("", "a") == 0
    assert longest_common_run("Hello, World!", "hello world") == 2


def test_overlap_window_is_sixteen_words() -> None:
    source = " ".join(f"w{i}" for i in range(40))
    fifteen = " ".join(f"w{i}" for i in range(10, 25))
    sixteen = " ".join(f"w{i}" for i in range(10, 26))
    assert not overlaps(fifteen, source)
    assert overlaps(sixteen, source)


def test_summary_is_built_from_facts() -> None:
    text = build_summary(
        repo_type="plugin",
        category="code_review",
        cause="reduce_errors",
        counts={"skills": 3, "hooks": 1},
        links=0,
        keywords=["diff", "pr"],
        tools=["Read", "Bash(git diff:*)"],
        license_id="MIT",
        last_commit="2026-10-10T00:00:00Z",
        archived=False,
        now=NOW,
    )
    assert text == (
        "Plugin de revisión de código con 3 skills y 1 hook. Sirve para reducir errores: diff, pr. "
        "Declara las herramientas Bash y Read; licencia MIT; último commit hace 2 días."
    )


def test_summary_variants() -> None:
    archived = build_summary(
        repo_type="awesome_list",
        category="development",
        cause="automate",
        counts={},
        links=1,
        keywords=[],
        tools=[],
        license_id=None,
        last_commit=None,
        archived=True,
        now=NOW,
    )
    assert archived.startswith(
        "Lista curada de desarrollo de software con 1 enlace a repositorios."
    )
    assert "Sin licencia; archivado por su autor." in archived
    market = build_summary(
        repo_type="marketplace",
        category="devops",
        cause="integrate",
        counts={"plugins": 2},
        links=0,
        keywords=["deploy"] * 40,
        tools=[f"Tool{i}" for i in range(30)],
        license_id="NOASSERTION",
        last_commit="2026-10-12T00:00:00Z",
        archived=False,
        now=NOW,
    )
    assert "que agrupa 2 plugins" in market
    assert len(market) <= 320


def test_when_items() -> None:
    skill = Artifact(
        "skill",
        "s/SKILL.md",
        "review-diff",
        True,
        description="Reviews diffs. Use when the user opens a pull request or asks for review.",
        has_when=True,
    )
    items = build_when("code_review", [skill])
    assert items[0] == "«review-diff» se activa con: pr y review."
    assert items[-1].startswith("Antes de fusionar")
    no_when = build_when(
        "testing", [Artifact("skill", "x/SKILL.md", "x", True, description="Tests.")]
    )
    assert no_when[-1].startswith("Ninguna descripción")
    assert trigger_words("No trigger here") == []
