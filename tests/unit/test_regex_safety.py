"""No regular expression applied to third-party text may take super-linear time (ReDoS).

A lazy prefix overlapping the next character class once made the analysis of one repository take
minutes and hung a live build (docs/investigacion.md E13). This test runs every compiled pattern
of the modules that read untrusted text against long hostile inputs, in a child process with a
time limit, so a new catastrophic pattern fails CI instead of freezing the pipeline.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

from analyzer.risk import SCRIPT_REF

ROOT = Path(__file__).resolve().parents[2]

CHECK = textwrap.dedent(
    """
    import importlib, re, sys, time
    MODULES = [
        "analyzer.text", "analyzer.frontmatter", "analyzer.validate", "analyzer.lexicon",
        "analyzer.taxonomy", "analyzer.language", "analyzer.risk", "analyzer.install",
        "analyzer.copyguard", "analyzer.summary", "analyzer.analyze", "analyzer.detect",
        "analyzer.scoring", "collector.social.base", "collector.http", "indexer.demand",
        "indexer.index", "pipeline.optout",
    ]
    found = {}
    def walk(name, value, depth=0):
        if isinstance(value, re.Pattern):
            found[name] = value
        elif depth < 3 and isinstance(value, (list, tuple, set, frozenset)):
            for i, item in enumerate(value):
                walk(f"{name}[{i}]", item, depth + 1)
        elif depth < 3 and isinstance(value, dict):
            for key, item in value.items():
                walk(f"{name}[{key!r}]", item, depth + 1)
    for module in MODULES:
        for key, value in vars(importlib.import_module(module)).items():
            walk(f"{module}.{key}", value)
    n = 20_000
    hostile = ["a" * n, " " * n, "-" * n, "`" * n, "[" * n, "https://" + "a" * n, "\\n" * n,
               "a." * (n // 2), "a/" * (n // 2), "a=" * (n // 2), " a" * (n // 2), "<" * n,
               "\\"'" * (n // 2), "ignore previous " * (n // 16),
               ("curl -s " + "x" * 40 + " | ") * (n // 50)]
    worst = (0.0, "")
    for name, pattern in found.items():
        start = time.perf_counter()
        for text in hostile:
            for _ in pattern.finditer(text):
                pass
        spent = time.perf_counter() - start
        worst = max(worst, (spent, name))
    print(len(found), round(worst[0], 3), worst[1])
    """
)


def test_every_pattern_is_linear_on_hostile_input() -> None:
    done = subprocess.run(  # noqa: S603 - fixed script run by our own interpreter
        [sys.executable, "-c", CHECK],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,  # a catastrophic pattern needs minutes on these inputs
        check=True,
    )
    count, worst, name = done.stdout.split()
    assert int(count) >= 80  # the walk really found the patterns
    assert float(worst) < 10, f"{name} took {worst} s"


def test_script_names_in_commands() -> None:
    def names(command: str) -> list[str]:
        return [m.group(1) for m in SCRIPT_REF.finditer(command)]

    assert names("bash ./scripts/check.sh") == ["check.sh"]
    assert names("${CLAUDE_PLUGIN_ROOT}/hooks/run-guard.sh --strict") == ["run-guard.sh"]
    assert names("sh -c 'x.sh && y.py'") == ["x.sh", "y.py"]
    assert names("echo hi") == []
