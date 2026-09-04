"""Gamification configuration constants.

Per the MVP spec (Appendix A/B/C) these values are intentionally kept out of the
awarding/evaluation code paths so the team can iterate on balance without a
migration. The tier table and badge catalog are also seeded into the database
(gam_tier_config / gam_badges) from these definitions so they can additionally
be edited at runtime; these serve as the source-of-truth seed and a safe
fallback.
"""

# --- Point values (Appendix A) -------------------------------------------------
# reason_key -> points awarded. Reversible order awards are clawed back with a
# negative ledger entry (see REASON_REVERSAL).
POINT_VALUES = {
    "order_completed_buyer": 50,
    "order_completed_seller": 100,
    "review_with_photo": 25,
    "review_text_only": 10,
    "post_created": 5,
    "post_reaction_received": 1,
    "profile_completed": 50,
    "referral_first_paid": 200,
    "daily_first_login": 2,
}

# Reason written when a previously-awarded order is refunded/cancelled.
REASON_ORDER_REVERSED = "order_reversed"

# --- Daily anti-abuse caps (Appendix A / 5.8) ---------------------------------
# reason_key -> max number of point-eligible awards per user per calendar day.
# Further events still succeed (e.g. the post publishes) but award 0 points.
DAILY_CAPS = {
    "post_created": 5,
    "post_reaction_received": 20,
}

# --- Reference types (ledger.ref_type) -----------------------------------------
REF_ORDER = "order"
REF_POST = "post"
REF_REVIEW = "review"
REF_USER = "user"
REF_REACTION = "reaction"

# --- Tiers / Stars (Appendix C) ------------------------------------------------
# Ordered ascending by min_lifetime_points. Colours are placeholders pending the
# Blink Graphics palette; the API exposes them so the client never hard-codes.
TIER_SEED = [
    {
        "tier": "newcomer",
        "name": "Newcomer",
        "star_count": 0,
        "min_lifetime_points": 0,
        "color_hex": "#5C677D",
    },
    {
        "tier": "hustler",
        "name": "Hustler",
        "star_count": 1,
        "min_lifetime_points": 100,
        "color_hex": "#A0522D",
    },
    {
        "tier": "trader",
        "name": "Trader",
        "star_count": 2,
        "min_lifetime_points": 500,
        "color_hex": "#9AA0A6",
    },
    {
        "tier": "merchant",
        "name": "Merchant",
        "star_count": 3,
        "min_lifetime_points": 1500,
        "color_hex": "#E36414",
    },
    {
        "tier": "magnate",
        "name": "Magnate",
        "star_count": 4,
        "min_lifetime_points": 5000,
        "color_hex": "#0F4C5C",
    },
    {
        "tier": "mogul",
        "name": "Mogul",
        "star_count": 5,
        "min_lifetime_points": 15000,
        "color_hex": "#3A86FF",
    },
]

DEFAULT_TIER_KEY = "newcomer"

# Early Bird badge window: users who joined within EARLY_BIRD_WINDOW_DAYS of the
# gamification launch qualify. (ISO date; adjust to the real launch date.)
GAMIFICATION_LAUNCH_DATE = "2026-07-01"
EARLY_BIRD_WINDOW_DAYS = 30

# --- Badge catalog (Appendix B) ------------------------------------------------
# audience: "S" seller, "B" buyer, "BS" either.
# criteria_json is a tiny DSL evaluated by badge_engine against a stats dict:
#   {"all": [{"stat": <name>, "op": <op>, "value": <n>}, ...], "trigger": [events]}
# "any" is also supported. Stats are assembled by services.get_badge_stats().
BADGE_SEED = [
    {
        "slug": "verified_seller",
        "name": "Verified Seller",
        "audience": "S",
        "category": "trust",
        "priority": 100,
        "description": "Completed identity verification.",
        "criteria_json": {
            "all": [{"stat": "is_verified_seller", "op": ">=", "value": 1}],
            "trigger": ["seller.verified", "order.completed"],
        },
    },
    {
        "slug": "first_sale",
        "name": "First Sale",
        "audience": "S",
        "category": "milestone",
        "priority": 60,
        "description": "Completed your first sale.",
        "criteria_json": {
            "all": [{"stat": "total_sales", "op": ">=", "value": 1}],
            "trigger": ["order.completed"],
        },
    },
    {
        "slug": "top_seller",
        "name": "Top Seller",
        "audience": "S",
        "category": "performance",
        "priority": 90,
        "description": "Completed 50 lifetime sales.",
        "criteria_json": {
            "all": [{"stat": "total_sales", "op": ">=", "value": 50}],
            "trigger": ["order.completed"],
        },
    },
    {
        "slug": "fast_shipper",
        "name": "Fast Shipper",
        "audience": "S",
        "category": "performance",
        "priority": 80,
        "description": "Average ship time under 24 hours over 10+ orders.",
        "criteria_json": {
            "all": [
                {"stat": "total_sales", "op": ">=", "value": 10},
                {"stat": "avg_ship_hours", "op": "<", "value": 24},
            ],
            "trigger": ["order.completed"],
        },
    },
    {
        "slug": "five_star_service",
        "name": "5-Star Service",
        "audience": "S",
        "category": "performance",
        "priority": 85,
        "description": "Average rating of 4.8+ over 20 or more reviews.",
        "criteria_json": {
            "all": [
                {"stat": "review_count", "op": ">=", "value": 20},
                {"stat": "avg_rating", "op": ">=", "value": 4.8},
            ],
            "trigger": ["review.created"],
        },
    },
    {
        "slug": "community_voice",
        "name": "Community Voice",
        "audience": "BS",
        "category": "milestone",
        "priority": 50,
        "description": "Earned 100 cumulative reactions on your posts.",
        "criteria_json": {
            "all": [{"stat": "total_reactions_received", "op": ">=", "value": 100}],
            "trigger": ["post.reaction_added"],
        },
    },
    {
        "slug": "trendsetter",
        "name": "Trendsetter",
        "audience": "S",
        "category": "performance",
        "priority": 70,
        "description": "A single post drove 5 or more orders.",
        # Attribution is a V2 mechanic; seeded inactive so it never mis-awards.
        "is_active": False,
        "criteria_json": {
            "all": [{"stat": "best_post_driven_orders", "op": ">=", "value": 5}],
            "trigger": ["order.completed"],
        },
    },
    {
        "slug": "early_bird",
        "name": "Early Bird",
        "audience": "BS",
        "category": "milestone",
        "priority": 40,
        "description": "Joined in the first month after launch.",
        "criteria_json": {
            "all": [{"stat": "is_early_member", "op": ">=", "value": 1}],
            "trigger": ["order.completed", "post.created", "profile.completed"],
        },
    },
    {
        "slug": "loyal_buyer",
        "name": "Loyal Buyer",
        "audience": "B",
        "category": "milestone",
        "priority": 55,
        "description": "Completed 10 purchases.",
        "criteria_json": {
            "all": [{"stat": "completed_purchases", "op": ">=", "value": 10}],
            "trigger": ["order.completed"],
        },
    },
    {
        "slug": "repeat_customer",
        "name": "Repeat Customer",
        "audience": "BS",
        "category": "milestone",
        "priority": 45,
        "description": "Bought from the same seller 3 or more times.",
        "criteria_json": {
            "all": [{"stat": "max_same_seller_purchases", "op": ">=", "value": 3}],
            "trigger": ["order.completed"],
        },
    },
]

# --- Redis key patterns (5.4) -------------------------------------------------
# Namespaced under "gam:" so gamification data can be flushed independently.
LB_SCOPE_GLOBAL = "global"
LB_SCOPE_BUYERS = "buyers"
LB_SCOPE_SELLERS = "sellers"
LB_SCOPES = (LB_SCOPE_GLOBAL, LB_SCOPE_BUYERS, LB_SCOPE_SELLERS)

LB_PERIOD_ALLTIME = "alltime"
LB_PERIOD_WEEKLY = "weekly"
LB_PERIODS = (LB_PERIOD_ALLTIME, LB_PERIOD_WEEKLY)

STATS_CACHE_TTL_SECONDS = 60


def lb_key(scope: str, period: str, period_key: str = None) -> str:
    """Redis sorted-set key for a leaderboard.

    All-time global has no period suffix; every other combination is keyed by
    the ISO week (e.g. '2026-W30').
    """
    if period == LB_PERIOD_ALLTIME:
        return f"gam:lb:{scope}:alltime"
    return f"gam:lb:{scope}:weekly:{period_key}"


def stats_cache_key(user_id: str) -> str:
    return f"gam:stats:{user_id}"


def ratelimit_key(reason: str, user_id: str, day: str) -> str:
    return f"gam:ratelimit:{reason}:{user_id}:{day}"
