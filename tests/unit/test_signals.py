from datetime import timedelta
from pathlib import Path

from pipeline.models import DemandItem, Mention
from pipeline.signals import SignalStore
from tests.support import NOW


def test_series_and_lookup(tmp_path: Path) -> None:
    store = SignalStore(tmp_path)
    store.record_repo("A/B", "2026-10-01", stars=10, forks=1, commits=3)
    store.record_repo("A/B", "2026-10-05", stars=15, forks=1, commits=4)
    assert store.series("a/b", "stars", ["2026-10-01", "2026-10-02", "2026-10-05"]) == [
        10,
        None,
        15,
    ]
    assert store.value_on_or_before("a/b", "stars", "2026-10-04") == 10
    assert store.value_on_or_before("a/b", "stars", "2026-09-01") == 10  # oldest available
    assert store.value_on_or_before("x/y", "stars", "2026-10-04") is None
    store.save()
    assert SignalStore(tmp_path).series("a/b", "forks", ["2026-10-05"]) == [1]


def test_mentions_are_deduplicated(tmp_path: Path) -> None:
    store = SignalStore(tmp_path)
    mention = Mention("hackernews", "k1", "a/b", "2026-10-10", 5)
    assert store.add_mentions([mention, mention]) == 1
    assert store.add_mentions([mention]) == 0
    assert store.mentions_by_repo()["a/b"][0].engagement == 5


def test_demand_and_npm(tmp_path: Path) -> None:
    store = SignalStore(tmp_path)
    item = DemandItem("stackexchange", "1", "2026-10-10T00:00:00Z", "text", title="t")
    assert store.add_demand([item]) == 1
    assert store.demand()[0].title == "t"
    assert store.npm_due("pkg", NOW)
    store.set_npm("pkg", 42, NOW)
    assert not store.npm_due("pkg", NOW + timedelta(hours=1))
    assert store.npm_due("pkg", NOW + timedelta(hours=25))
    assert store.npm_downloads("pkg") == 42
    assert store.npm_downloads(None) is None


def test_prune_retention(tmp_path: Path) -> None:
    store = SignalStore(tmp_path)
    store.record_repo("a/b", "2026-01-01", stars=1, forks=0, commits=0)
    store.record_repo("a/b", "2026-10-11", stars=2, forks=0, commits=0)
    store.record_repo("gone/repo", "2026-10-11", stars=2, forks=0, commits=0)
    store.add_mentions(
        [Mention("hn", "old", "a/b", "2026-01-01"), Mention("hn", "new", "a/b", "2026-10-10")]
    )
    store.add_demand(
        [
            DemandItem("stackexchange", "old", "2025-01-01T00:00:00Z", "x"),
            DemandItem("stackexchange", "new", "2026-10-01T00:00:00Z", "y"),
        ]
    )
    store.prune(NOW, keep_repos={"a/b"})
    assert list(store.data["repos"]) == ["a/b"]
    assert store.series("a/b", "stars", ["2026-01-01", "2026-10-11"]) == [None, 2]
    assert list(store.data["mentions"]) == ["new"]
    assert [d.id for d in store.demand()] == ["new"]
