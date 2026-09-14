"""Tests for saved posts / wishlisted products."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.libs.errors import NotFoundError, ValidationError
from app.socials.models import SavedItemType
from app.socials.services import SavedItemService


@patch("app.socials.services.session_scope")
def test_save_creates_a_row(mock_scope):
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.side_effect = [
        ("PST_1",),  # content exists
        None,  # not already saved
    ]
    mock_scope.return_value.__enter__.return_value = session

    result = SavedItemService.save("USR_A", "post", "PST_1")

    assert result == {
        "saved": True,
        "content_type": "post",
        "content_id": "PST_1",
    }
    session.add.assert_called_once()


@patch("app.socials.services.session_scope")
def test_saving_twice_is_a_no_op(mock_scope):
    """Same intent as saving once, so it reports success rather than 409."""
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.side_effect = [
        ("PRD_1",),  # content exists
        SimpleNamespace(user_id="USR_A"),  # already saved
    ]
    mock_scope.return_value.__enter__.return_value = session

    result = SavedItemService.save("USR_A", "product", "PRD_1")

    assert result["saved"] is True
    session.add.assert_not_called()


@patch("app.socials.services.session_scope")
def test_save_rejects_missing_content(mock_scope):
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(NotFoundError):
        SavedItemService.save("USR_A", "product", "PRD_GONE")


def test_unknown_content_type_is_rejected():
    with pytest.raises(ValidationError):
        SavedItemService._resolve_type("banana")


@patch("app.socials.services.session_scope")
def test_saved_ids_is_empty_without_a_user(mock_scope):
    """Anonymous list rendering must not hit the database at all."""
    assert SavedItemService.saved_ids(None, "product", ["PRD_1"]) == set()
    assert SavedItemService.saved_ids("USR_A", "product", []) == set()
    mock_scope.assert_not_called()


@patch("app.socials.services.session_scope")
def test_saved_ids_returns_matches(mock_scope):
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [
        ("PRD_1",),
        ("PRD_3",),
    ]
    mock_scope.return_value.__enter__.return_value = session

    got = SavedItemService.saved_ids("USR_A", "product", ["PRD_1", "PRD_2", "PRD_3"])

    assert got == {"PRD_1", "PRD_3"}


def test_saved_item_type_values():
    assert {t.value for t in SavedItemType} == {"post", "product"}
