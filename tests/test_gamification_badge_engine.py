"""Unit tests for the pure badge criteria DSL evaluator. No DB/Redis needed."""

import pytest

from app.gamification.badge_engine import evaluate, triggers, progress


# --- evaluate: all / any --------------------------------------------------- #
def test_all_conditions_met():
    criteria = {
        "all": [
            {"stat": "total_sales", "op": ">=", "value": 10},
            {"stat": "avg_ship_hours", "op": "<", "value": 24},
        ]
    }
    assert evaluate(criteria, {"total_sales": 10, "avg_ship_hours": 23}) is True


def test_all_conditions_one_fails():
    criteria = {
        "all": [
            {"stat": "total_sales", "op": ">=", "value": 10},
            {"stat": "avg_ship_hours", "op": "<", "value": 24},
        ]
    }
    # ship hours exactly 24 fails strict "<"
    assert evaluate(criteria, {"total_sales": 10, "avg_ship_hours": 24}) is False
    # sales below threshold fails
    assert evaluate(criteria, {"total_sales": 9, "avg_ship_hours": 1}) is False


def test_any_conditions():
    criteria = {
        "any": [
            {"stat": "a", "op": ">=", "value": 5},
            {"stat": "b", "op": ">=", "value": 5},
        ]
    }
    assert evaluate(criteria, {"a": 5, "b": 0}) is True
    assert evaluate(criteria, {"a": 0, "b": 9}) is True
    assert evaluate(criteria, {"a": 0, "b": 0}) is False


def test_all_and_any_combined():
    criteria = {
        "all": [{"stat": "x", "op": ">=", "value": 1}],
        "any": [
            {"stat": "y", "op": "==", "value": 2},
            {"stat": "z", "op": "==", "value": 3},
        ],
    }
    assert evaluate(criteria, {"x": 1, "y": 2, "z": 0}) is True
    assert evaluate(criteria, {"x": 0, "y": 2}) is False  # all fails
    assert evaluate(criteria, {"x": 1, "y": 0, "z": 0}) is False  # any fails


# --- evaluate: edge cases -------------------------------------------------- #
def test_missing_stat_treated_as_zero():
    criteria = {"all": [{"stat": "total_sales", "op": ">=", "value": 1}]}
    assert evaluate(criteria, {}) is False


def test_empty_criteria_is_false():
    assert evaluate({}, {"anything": 100}) is False
    assert evaluate(None, {"anything": 100}) is False


def test_criteria_with_only_trigger_is_not_awardable():
    # No condition groups -> cannot be awarded on stats alone.
    assert evaluate({"trigger": ["order.completed"]}, {"x": 1}) is False


def test_unknown_operator_is_false():
    assert evaluate({"all": [{"stat": "x", "op": "~=", "value": 1}]}, {"x": 1}) is False


@pytest.mark.parametrize(
    "op,stat,value,expected",
    [
        (">=", 5, 5, True),
        (">=", 4, 5, False),
        (">", 6, 5, True),
        (">", 5, 5, False),
        ("<=", 5, 5, True),
        ("<=", 6, 5, False),
        ("<", 4, 5, True),
        ("<", 5, 5, False),
        ("==", 5, 5, True),
        ("==", 5, 6, False),
        ("!=", 5, 6, True),
        ("!=", 5, 5, False),
    ],
)
def test_all_operators(op, stat, value, expected):
    criteria = {"all": [{"stat": "s", "op": op, "value": value}]}
    assert evaluate(criteria, {"s": stat}) is expected


def test_non_numeric_stat_defaults_to_zero():
    criteria = {"all": [{"stat": "s", "op": ">=", "value": 1}]}
    assert evaluate(criteria, {"s": "not-a-number"}) is False
    assert evaluate(criteria, {"s": None}) is False


# --- triggers -------------------------------------------------------------- #
def test_triggers_returns_list():
    assert triggers({"trigger": ["order.completed", "review.created"]}) == [
        "order.completed",
        "review.created",
    ]


def test_triggers_empty_when_absent():
    assert triggers({"all": []}) == []
    assert triggers(None) == []


# --- progress -------------------------------------------------------------- #
def test_progress_threshold_ratio():
    criteria = {"all": [{"stat": "total_sales", "op": ">=", "value": 50}]}
    assert progress(criteria, {"total_sales": 25}) == pytest.approx(0.5)
    assert progress(criteria, {"total_sales": 0}) == 0.0


def test_progress_caps_at_one():
    criteria = {"all": [{"stat": "total_sales", "op": ">=", "value": 10}]}
    assert progress(criteria, {"total_sales": 999}) == 1.0


def test_progress_uses_binding_constraint():
    # Two conditions -> the minimum ratio drives the bar.
    criteria = {
        "all": [
            {"stat": "a", "op": ">=", "value": 10},
            {"stat": "b", "op": ">=", "value": 100},
        ]
    }
    # a is 100% (10/10), b is 20% (20/100) -> min = 0.2
    assert progress(criteria, {"a": 10, "b": 20}) == pytest.approx(0.2)


def test_progress_less_than_op_met_or_unmet():
    criteria = {"all": [{"stat": "avg_ship_hours", "op": "<", "value": 24}]}
    assert progress(criteria, {"avg_ship_hours": 12}) == 1.0
    assert progress(criteria, {"avg_ship_hours": 30}) == 0.0


def test_progress_zero_target_is_complete():
    criteria = {"all": [{"stat": "x", "op": ">=", "value": 0}]}
    assert progress(criteria, {"x": 0}) == 1.0


def test_progress_empty_criteria_is_zero():
    assert progress({}, {"x": 5}) == 0.0
    assert progress(None, {"x": 5}) == 0.0
