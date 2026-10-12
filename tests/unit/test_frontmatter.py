from analyzer.frontmatter import MAX_FRONTMATTER, parse


def test_valid_frontmatter_and_body() -> None:
    fm = parse("---\nname: a\ndescription: b\n---\n\n# Title\n")
    assert fm.present and fm.error is None
    assert fm.fields == {"name": "a", "description": "b"}
    assert fm.body.strip() == "# Title"
    assert fm.body_line == 5


def test_frontmatter_must_be_first_line() -> None:
    fm = parse("\n---\nname: a\n---\n")
    assert not fm.present


def test_bom_is_ignored() -> None:
    assert parse("﻿---\nname: a\n---\n").fields == {"name": "a"}


def test_aliases_are_rejected() -> None:
    fm = parse("---\na: &x [1, 2]\nb: [*x, *x]\n---\n")
    assert fm.error == "anchors/aliases not allowed"
    assert fm.fields == {}


def test_unclosed_and_oversized() -> None:
    assert parse("---\nname: a\n").error == "frontmatter not closed"
    huge = "---\n" + ("k: v\n" * (MAX_FRONTMATTER // 4)) + "---\n"
    assert parse(huge).error == "frontmatter too large"


def test_invalid_yaml_and_non_mapping() -> None:
    bad = parse("---\ndescription: one: two\n---\n")
    assert bad.error is not None and bad.error.startswith("invalid yaml")
    assert parse("---\n- a\n- b\n---\n").error == "frontmatter is not a mapping"
    assert parse("---\n---\nbody").fields == {}


def test_python_tags_are_not_constructed() -> None:
    fm = parse("---\nx: !!python/object/apply:os.system ['echo hi']\n---\n")
    assert fm.error is not None
