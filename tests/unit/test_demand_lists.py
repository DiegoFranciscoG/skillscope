import pytest

from indexer.demand import (
    attach_supply,
    category_demand,
    cluster,
    gaps,
    item_weight,
    matched_demand,
    relevant,
)
from indexer.embeddings import build_lsa
from indexer.lists import Ranked, all_lists, most_needed
from pipeline.models import DemandItem


def q(
    item_id: str, text: str, tags: list[str], *, answered: bool = False, day: int = 1
) -> DemandItem:
    return DemandItem(
        source="stackexchange",
        id=item_id,
        created_at=f"2026-10-{day:02d}T00:00:00Z",
        text=f"{text} {' '.join(tags)}",
        answered=answered,
        tags=tags,
        title=text,
        url=f"https://stackoverflow.com/q/{item_id}",
        author="someone",
    )


QUESTIONS = [
    q("1", "Migrate COBOL batch jobs to Java", ["cobol", "migration", "claude-code"], day=1),
    q("2", "COBOL mainframe migration with an agent", ["cobol", "mainframe"], day=2),
    q("3", "Review pull requests automatically", ["code-review", "pull-request"], day=3),
    q("4", "Terraform plan security checks", ["terraform", "security"], answered=True, day=4),
]


def test_item_weight() -> None:
    assert item_weight(QUESTIONS[0]) == 1.0
    assert item_weight(QUESTIONS[3]) == 0.5
    reddit = DemandItem("reddit", "testing:2026-10-01", "2026-10-01T00:00:00Z", "tests", count=3)
    assert item_weight(reddit) == pytest.approx(2.4)


def test_cluster_groups_similar_questions_and_ignores_generic_tags() -> None:
    topics = cluster(QUESTIONS)
    labels = [t.label for t in topics]
    assert labels[0] == "cobol, migration, mainframe"
    cobol = topics[0]
    assert len(cobol.items) == 2 and cobol.demand == 2.0
    assert "claud" not in " ".join(cobol.subjects)
    assert {"cobol", "migration"} <= set(cobol.subjects)


def test_supply_and_gaps() -> None:
    model = build_lsa(
        [
            ("a/pr", "review pull requests diff code review"),
            ("b/tf", "terraform plan security checkov iac"),
            ("c/x", "unrelated notes calendar"),
        ]
    )
    repo_tokens = [{"review", "pr", "diff", "cod"}, {"terraform", "security", "plan"}, {"not"}]
    topics = cluster(QUESTIONS)
    attach_supply(topics, model, repo_tokens, [80, 70, 90])
    supply = {t.label: t.supply for t in topics}
    assert supply["code-review, pull-request"] == ["a/pr"]
    assert supply["terraform, security"] == ["b/tf"]
    assert [t.label for t in gaps(topics)] == ["cobol, migration, mainframe"]
    attach_supply(topics, model, repo_tokens, [10, 10, 10])  # low scores do not count as supply
    assert all(not t.supply for t in topics)


def test_matched_demand_needs_meaning_and_a_shared_word() -> None:
    model = build_lsa(
        [
            ("a/pr", "review pull requests diff code review reviewer"),
            ("b/pr2", "pull requests review comments"),
            ("c/notes", "calendar meeting notes email"),
            ("d/notes2", "email inbox notes meeting"),
        ]
    )
    tokens = [{"review", "pr", "diff"}, {"pr", "review"}, {"email"}, {"email"}]
    weights, matches = matched_demand(model, QUESTIONS, tokens)
    assert weights[0] >= 1.0 and matches[0] == ["stackexchange:3"]
    assert weights[2] == 0.0


def test_category_demand() -> None:
    totals = category_demand(QUESTIONS)
    assert totals["code_review"] == 1.0
    assert totals["security"] == 0.5  # "terraform security" leans to security
    assert sum(totals.values()) == 3.5


def _ranked(**overrides: object) -> Ranked:
    base = {
        "id": "a/a",
        "type": "skill",
        "category": "testing",
        "total": 60,
        "quality": 20.0,
        "adoption": 10.0,
        "social": 0.0,
        "utility": 5.0,
        "penalty": 0,
        "stars": 10,
        "mentions_30d": 0.0,
        "trend": 0.0,
    }
    base.update(overrides)
    return Ranked(**base)  # type: ignore[arg-type]


def test_lists_criteria() -> None:
    items = [
        _ranked(id="a/used", adoption=19, stars=900, total=70),
        _ranked(id="b/mentioned", mentions_30d=3.0, social=8, trend=0.5),
        _ranked(id="c/risky", penalty=18, total=30, stars=5000),
        _ranked(id="d/list", type="awesome_list", total=80),
        _ranked(id="e/useful", utility=20, quality=25, total=65),
    ]
    lists = all_lists(items, {"testing": 4.0})
    assert lists["most_used"][0] == "a/used"
    assert lists["most_mentioned"] == ["b/mentioned"]
    assert lists["trending"] == ["b/mentioned"]
    assert lists["most_useful"][0] == "e/useful"
    assert "d/list" not in lists["safest"] and "c/risky" not in lists["safest"]
    assert lists["riskiest"] == ["c/risky"]
    needed = most_needed(items, {"testing": 4.0, "security": 3.0})
    assert needed[0]["category"] == "security"  # no supply at all
    assert needed[0]["ratio"] == 3.0


def test_only_agent_questions_count_as_demand() -> None:
    assert relevant(q("10", "Copy constructor rules", ["c++", "claude-code"]))  # agent tag
    assert relevant(q("11", "Automate COBOL migration with an agent", ["cobol"]))
    assert relevant(q("12", "Expose tools over MCP from Spring", ["spring"]))
    assert not relevant(q("13", "Is deleting both copy constructors redundant?", ["c++"]))
    assert not relevant(q("14", "Set the User-Agent header in requests", ["python"]))
    assert not relevant(q("15", "ssh agent forwarding breaks git", ["ssh"]))


def test_generic_tags_measured_on_the_data_do_not_make_supply() -> None:
    ids = [f"r/{i}" for i in range(24)]
    model = build_lsa([(i, "python tooling library") for i in ids])
    repo_tokens = [{"python", "tool"} for _ in ids]  # python is in every repository
    repo_tokens[0] |= {"pydantic"}
    topics = cluster(
        [
            q("20", "Validate agent output with Pydantic", ["python", "pydantic"], day=1),
            q("21", "Pydantic models for agent tools", ["python", "pydantic"], day=2),
            q("22", "Best way to write python with an agent", ["python"], day=3),
            q("23", "Python agent tips please", ["python"], day=4),
        ]
    )
    attach_supply(topics, model, repo_tokens, [80] * len(ids))
    by_label = {t.label: t for t in topics}
    assert by_label["pydantic"].specific == ["pydantic"]
    assert by_label["pydantic"].supply == ["r/0"]  # not every python repository
    vague = by_label["python"]
    assert vague.specific == [] and vague.demand >= 2
    assert gaps(topics) == []  # demand without a specific subject is not a gap
