import pytest

from collector.budget import Budget, BudgetExhaustedError


def test_spend_until_limit_then_refuse() -> None:
    budget = Budget("x", 2)
    budget.ensure()
    budget.spend()
    budget.ensure()
    budget.spend()
    assert not budget.can_spend()
    with pytest.raises(BudgetExhaustedError):
        budget.ensure()


def test_cap_keeps_ten_percent_reserve() -> None:
    budget = Budget("core", 140)
    budget.cap(api_remaining=120, api_limit=1000)
    # reserve = 100, so only 20 calls may be spent this build
    assert budget.limit == 20
    budget.cap(api_remaining=5000, api_limit=5000)
    assert budget.limit == 20  # never grows above the configured value


def test_observe_closes_at_reserve() -> None:
    budget = Budget("search", 24)
    budget.observe(remaining=4, limit=30)
    assert not budget.closed  # reserve of 30 is 3
    budget.observe(remaining=3, limit=30)
    assert budget.closed
    assert "reserve" in (budget.closed_reason or "")
    with pytest.raises(BudgetExhaustedError):
        budget.ensure()


def test_observe_ignores_missing_headers() -> None:
    budget = Budget("x", 5)
    budget.observe(remaining=None, limit=None)
    assert not budget.closed


def test_report_shape() -> None:
    budget = Budget("x", 3)
    budget.spend()
    assert budget.report() == {
        "budget": 3,
        "used": 1,
        "calls": 1,
        "closed": None,
        "api_remaining": None,
    }
