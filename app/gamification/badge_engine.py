"""Criteria DSL evaluator for badges (spec §4.3, Appendix B).

criteria_json shape:
    {
      "all": [{"stat": "total_sales", "op": ">=", "value": 10}, ...],   # AND
      "any": [{...}, ...],                                              # OR
      "trigger": ["order.completed", ...]
    }

Stats are a flat dict of {stat_name: number}; a missing stat is treated as 0.
Everything here is pure so it is trivially unit-testable.
"""

from typing import Dict, List

_OPS = {
    ">=": lambda a, b: a >= b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


def _stat_value(stats: Dict, name: str) -> float:
    try:
        return float(stats.get(name, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _check(condition: Dict, stats: Dict) -> bool:
    op = _OPS.get(condition.get("op"))
    if op is None:
        return False
    return op(
        _stat_value(stats, condition.get("stat")), float(condition.get("value", 0))
    )


def evaluate(criteria: Dict, stats: Dict) -> bool:
    """Return True if the user's stats satisfy the criteria."""
    if not criteria:
        return False

    all_conds = criteria.get("all") or []
    any_conds = criteria.get("any") or []

    if all_conds and not all(_check(c, stats) for c in all_conds):
        return False
    if any_conds and not any(_check(c, stats) for c in any_conds):
        return False
    # Must have at least one condition group to be awardable.
    return bool(all_conds or any_conds)


def triggers(criteria: Dict) -> List[str]:
    """Events that should re-evaluate this badge."""
    if not criteria:
        return []
    return list(criteria.get("trigger") or [])


def progress(criteria: Dict, stats: Dict) -> float:
    """Best-effort 0..1 progress for locked-badge display.

    Uses the minimum ratio across the "all" conditions (the binding constraint).
    Non-threshold ops (<, ==) that are already satisfied count as complete;
    otherwise they contribute 0 so the badge reads as incomplete.
    """
    conds = (criteria or {}).get("all") or (criteria or {}).get("any") or []
    if not conds:
        return 0.0

    ratios = []
    for c in conds:
        target = float(c.get("value", 0) or 0)
        current = _stat_value(stats, c.get("stat"))
        op = c.get("op")
        if op in (">=", ">"):
            ratios.append(1.0 if target <= 0 else min(1.0, current / target))
        else:
            # For "less than / equals" style gates, we can't show a smooth bar;
            # collapse to met/unmet.
            ratios.append(1.0 if _check(c, stats) else 0.0)
    return round(min(ratios), 4) if ratios else 0.0
