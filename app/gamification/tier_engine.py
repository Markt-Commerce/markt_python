"""Pure functions mapping lifetime points to a tier (spec 4.2).

No database or Redis access here so these are trivially unit-testable. Callers
pass in the tier rows (from gam_tier_config, cached) as a list of dicts:
    {"tier", "name", "star_count", "min_lifetime_points", "color_hex"}
"""

from typing import List, Dict, Optional

from .constants import TIER_SEED, DEFAULT_TIER_KEY


def _sorted_rows(tier_rows: List[Dict]) -> List[Dict]:
    return sorted(tier_rows or TIER_SEED, key=lambda r: r["min_lifetime_points"])


def compute_tier(lifetime_points: int, tier_rows: List[Dict] = None) -> Dict:
    """Return the highest tier whose threshold is <= lifetime_points."""
    rows = _sorted_rows(tier_rows)
    current = rows[0]
    for row in rows:
        if lifetime_points >= row["min_lifetime_points"]:
            current = row
        else:
            break
    return current


def next_tier(lifetime_points: int, tier_rows: List[Dict] = None) -> Optional[Dict]:
    """Return the next tier above the current one, or None at the top tier."""
    rows = _sorted_rows(tier_rows)
    for row in rows:
        if row["min_lifetime_points"] > lifetime_points:
            return row
    return None


def tier_progress(lifetime_points: int, tier_rows: List[Dict] = None) -> Dict:
    """Full progression view for the profile header.

    Returns the current tier row plus progress_to_next (0..1) and
    points_to_next_tier. At the top tier progress is 1.0 and points_to_next is 0.
    """
    rows = _sorted_rows(tier_rows)
    current = compute_tier(lifetime_points, rows)
    nxt = next_tier(lifetime_points, rows)

    if nxt is None:
        return {
            "current": current,
            "next": None,
            "progress_to_next": 1.0,
            "points_to_next_tier": 0,
        }

    span = nxt["min_lifetime_points"] - current["min_lifetime_points"]
    gained = lifetime_points - current["min_lifetime_points"]
    progress = 0.0 if span <= 0 else max(0.0, min(1.0, gained / span))
    return {
        "current": current,
        "next": nxt,
        "progress_to_next": round(progress, 4),
        "points_to_next_tier": max(0, nxt["min_lifetime_points"] - lifetime_points),
    }


def tier_key_for(lifetime_points: int, tier_rows: List[Dict] = None) -> str:
    row = compute_tier(lifetime_points, tier_rows)
    return row.get("tier", DEFAULT_TIER_KEY)
