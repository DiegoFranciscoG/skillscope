import json

import pytest

from analyzer.text import fold, is_generic, keywords, normalize, stem, tokens, words
from tests.support import SAMPLES

CASES = json.loads((SAMPLES / "tokenize-cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c["input"] or "blank" for c in CASES])
def test_shared_tokenizer_cases(case: dict[str, object]) -> None:
    """Same file is checked by Vitest so Python and TypeScript stay identical."""
    assert tokens(str(case["input"])) == case["tokens"]


def test_fold_and_phrases() -> None:
    assert fold("Diseño Ágil") == "diseno agil"
    assert "pr" in normalize("Two pull-requests").split()
    assert "database" in normalize("bases de datos").split()


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("tests", "test"),
        ("testing", "test"),
        ("tested", "test"),
        ("running", "run"),
        ("libraries", "library"),
        ("classes", "class"),
        ("analysis", "analysis"),
        ("code", "cod"),
        ("coding", "cod"),
        ("pr", "pr"),
        ("sql", "sql"),
    ],
)
def test_stem(word: str, expected: str) -> None:
    assert stem(word) == expected


def test_words_map_spanish_to_english() -> None:
    assert words("revisar la documentación de seguridad") == ["review", "docs", "security"]


def test_keywords_drop_generic_words() -> None:
    assert keywords("A skill that lets the user review pull requests") == ["review", "pr"]
    assert is_generic("skills")
    assert not is_generic("pr")
