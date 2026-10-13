from pathlib import Path

from pipeline import optout


def test_from_file_ignores_comments(tmp_path: Path) -> None:
    path = tmp_path / "optout.txt"
    path.write_text("# owners asked\nOwner/Repo  # 2026-10-01\n\nnot-a-repo\n", encoding="utf-8")
    assert optout.from_file(path) == {"owner/repo"}
    assert optout.from_file(tmp_path / "missing.txt") == set()


def test_issue_from_owner_is_accepted_automatically() -> None:
    issues = [
        {
            "body": "### Repositorio\n\nhttps://github.com/Alice/my-skill",
            "user": {"login": "alice"},
        },
        {"body": "Please remove bob/tool", "user": {"login": "mallory"}, "labels": []},
        {
            "body": "carol/plugin",
            "user": {"login": "someone"},
            "labels": [{"name": "opt-out-approved"}],
        },
        {"body": "x/y", "user": {"login": "x"}, "pull_request": {}},
    ]
    assert optout.from_issues(issues) == {"alice/my-skill", "carol/plugin"}


def test_repo_from_issue_parsing() -> None:
    assert optout.repo_from_issue("see https://github.com/a/b.git.") == "a/b"
    assert optout.repo_from_issue("nothing here") is None


def test_topic_optout() -> None:
    assert optout.has_optout_topic(["Skillscope-OptOut"])
    assert not optout.has_optout_topic(["claude-skills"])


def test_issue_form_body_is_parsed() -> None:
    body = (
        "### Repositorio\n\nAcme-Labs/my.skill\n\n"
        "### Motivo (opcional)\n\nYa no lo mantengo; ver other/repo"
    )
    issue = {"body": body, "user": {"login": "acme-labs"}, "labels": [{"name": "opt-out"}]}
    assert optout.from_issues([issue]) == {"acme-labs/my.skill"}
