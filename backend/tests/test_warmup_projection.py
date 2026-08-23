"""The warmup runner's balance projection.

The point of the projection is to say "this run will not finish" at the first
25-query increment that shows it, rather than after the balance is gone. The
arithmetic is therefore worth pinning: an off-by-one in the wrong direction
either cries wolf or lets a run walk into a wall.
"""
import pytest

from scripts.warmup_run import project


def test_a_run_within_budget_raises_nothing():
    p = project(sent=25, target=1000, spent=0.10, remaining=50.0)
    assert p["per_query"] == pytest.approx(0.004)
    assert p["short"] == 0
    assert p["shortfall"] == 0.0


def test_a_run_that_cannot_finish_reports_how_far_short():
    # 0.02/query, 975 to go = 19.50 needed, 2.00 in hand.
    p = project(sent=25, target=1000, spent=0.50, remaining=2.00)
    assert p["per_query"] == pytest.approx(0.02)
    assert p["affordable"] == 100
    assert p["short"] == 875
    assert p["cost_to_finish"] == pytest.approx(19.50)
    assert p["shortfall"] == pytest.approx(17.50)


def test_no_spend_yet_projects_nothing():
    """A free-tier or cached increment must not read as 'infinite budget' via a
    divide-by-zero, nor as a spurious warning."""
    p = project(sent=25, target=1000, spent=0.0, remaining=5.0)
    assert p["per_query"] == 0.0
    assert p["affordable"] is None
    assert p["short"] == 0


def test_nothing_sent_yet_is_not_a_division_error():
    p = project(sent=0, target=1000, spent=0.0, remaining=5.0)
    assert p["per_query"] == 0.0
    assert p["to_go"] == 1000


def test_a_finished_run_has_nothing_left_to_fund():
    p = project(sent=1000, target=1000, spent=20.0, remaining=0.01)
    assert p["to_go"] == 0
    assert p["short"] == 0
    assert p["cost_to_finish"] == 0.0
    assert p["shortfall"] == 0.0


def test_exactly_affordable_is_not_flagged():
    """Boundary: the balance covers the remainder to the penny."""
    p = project(sent=25, target=50, spent=0.25, remaining=0.25)
    assert p["per_query"] == pytest.approx(0.01)
    assert p["affordable"] == 25
    assert p["to_go"] == 25
    assert p["short"] == 0
