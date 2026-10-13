from collector.budget import Budget
from collector.github.client import GitHubBudgets
from collector.github.discovery import FRONTIER_FULL
from collector.run import CATCH_UP_MIN_LIMIT, catching_up
from pipeline.config import Budgets


def _budgets(limit: int) -> GitHubBudgets:
    budgets = GitHubBudgets.from_settings(Budgets())
    for budget in (budgets.core, budgets.graphql):
        budget.observe(remaining=limit - 10, limit=limit)
    return budgets


def test_catch_up_needs_a_long_queue_and_a_personal_token_quota() -> None:
    assert catching_up(_budgets(CATCH_UP_MIN_LIMIT), FRONTIER_FULL)
    assert not catching_up(_budgets(CATCH_UP_MIN_LIMIT), FRONTIER_FULL - 1)
    assert not catching_up(_budgets(1000), FRONTIER_FULL)  # repository GITHUB_TOKEN


def test_no_catch_up_after_a_rate_limit() -> None:
    budgets = _budgets(CATCH_UP_MIN_LIMIT)
    budgets.graphql.close("retry-after")
    assert not catching_up(budgets, FRONTIER_FULL)
    assert isinstance(budgets.core, Budget)
