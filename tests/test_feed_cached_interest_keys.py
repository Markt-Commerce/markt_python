"""Cached interests and preferences keep integer category-id keys.

JSON stringifies object keys, so without conversion a warm cache returned
{"12": 3}, every `category_id in interests` check failed, and the feed was
ranked differently cold vs warm.
"""

import json
from unittest.mock import patch

from app.socials.services import FeedService, _category_keys_to_int


def test_keys_restored_to_int():
    assert _category_keys_to_int({"12": 3, "7": 1}) == {12: 3, 7: 1}


def test_non_numeric_keys_left_alone():
    assert _category_keys_to_int({"fashion": 2, 4: 1}) == {"fashion": 2, 4: 1}


def test_cached_interests_match_integer_category_ids():
    cached = json.dumps({12: 3, 7: 1})  # what _get_user_interests stores
    with patch("app.socials.services.redis_client") as redis:
        redis.get.return_value = cached
        interests = FeedService._get_user_interests("USR_1")
    assert 12 in interests and interests[12] == 3


def test_cached_category_preferences_match_integer_ids():
    cached = json.dumps({"category_preferences": {12: 5}, "followed_sellers": []})
    with patch("app.socials.services.redis_client") as redis:
        redis.get.return_value = cached
        prefs = FeedService._get_user_preferences("USR_1")
    assert prefs["category_preferences"] == {12: 5}
    assert prefs["followed_sellers"] == []
