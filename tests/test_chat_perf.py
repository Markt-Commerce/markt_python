"""Tests for the chat list and detail read paths.

These cover the three defects the N+1 work turned up, not the query counts
themselves — a count assertion would break on any unrelated refactor, while
these break only if the behaviour regresses.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.chats.services import ChatService


def test_batch_unread_counts_is_one_query_keyed_by_room():
    """One grouped query for every room, not one query per room.

    The old path called _get_unread_count() per room, and that helper opened its
    own session_scope. Each room therefore cost a query *and* a commit, and the
    commit expired the rooms and users already loaded — so the rendering loop
    re-fetched them a row at a time.
    """
    session = MagicMock()
    chain = session.query.return_value.filter.return_value.group_by.return_value
    chain.all.return_value = [(1, 3), (2, 0), (7, 12)]

    counts = ChatService._batch_unread_counts(session, [1, 2, 7], "USR_1")

    assert counts == {1: 3, 2: 0, 7: 12}
    assert session.query.call_count == 1


def test_batch_unread_counts_short_circuits_on_no_rooms():
    session = MagicMock()
    assert ChatService._batch_unread_counts(session, [], "USR_1") == {}
    session.query.assert_not_called()


def test_batch_offers_short_circuits_on_no_messages():
    session = MagicMock()
    assert ChatService._batch_offers(session, []) == {}
    session.query.assert_not_called()


def test_batch_offers_keys_by_message_id():
    session = MagicMock()
    offers = [SimpleNamespace(message_id=5), SimpleNamespace(message_id=9)]
    session.query.return_value.filter.return_value.all.return_value = offers

    keyed = ChatService._batch_offers(session, [5, 9])

    assert set(keyed) == {5, 9}
    assert session.query.call_count == 1


def test_batch_last_messages_short_circuits_on_no_rooms():
    session = MagicMock()
    assert ChatService._batch_last_messages(session, []) == {}
    session.query.assert_not_called()


@patch("app.chats.services.ChatService._batch_unread_counts", return_value={})
@patch("app.chats.services.ChatService._batch_last_messages", return_value={})
@patch("app.chats.services.read_scope")
def test_counterparty_is_only_a_seller_when_they_have_a_seller_account(
    mock_scope, _last, _unread
):
    """`hasattr(user, "seller_account")` is always True.

    The attribute exists on the model whether or not it resolves to a row, so
    the old check reported every counterparty as a seller — buyers included.
    """
    buyer = SimpleNamespace(
        id="USR_BUYER",
        username="ada",
        profile_picture=None,
        seller_account=None,
    )
    room = SimpleNamespace(
        id=1,
        buyer_id="USR_ME",
        seller_id="USR_BUYER",
        buyer=None,
        seller=buyer,
        product=None,
        request=None,
        last_message_at=None,
    )

    session = MagicMock()
    query = session.query.return_value
    query.options.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
        room
    ]
    query.filter.return_value.count.return_value = 1
    mock_scope.return_value.__enter__.return_value = session

    result = ChatService.get_user_chat_rooms("USR_ME", 1, 20)

    assert result["rooms"][0]["other_user"]["is_seller"] is False


@patch("app.chats.services.ChatService._batch_unread_counts", return_value={})
@patch("app.chats.services.ChatService._batch_last_messages", return_value={})
@patch("app.chats.services.read_scope")
def test_pagination_total_counts_all_rooms_not_just_the_page(
    mock_scope, _last, _unread
):
    """total used to report len(page), so a full page and the last page looked
    identical and the client could never tell when to stop paging."""
    room = SimpleNamespace(
        id=1,
        buyer_id="USR_ME",
        seller_id="USR_OTHER",
        buyer=None,
        seller=SimpleNamespace(
            id="USR_OTHER", username="b", profile_picture=None, seller_account=None
        ),
        product=None,
        request=None,
        last_message_at=None,
    )

    session = MagicMock()
    query = session.query.return_value
    query.options.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
        room
    ]
    query.filter.return_value.count.return_value = 57
    mock_scope.return_value.__enter__.return_value = session

    result = ChatService.get_user_chat_rooms("USR_ME", 1, 20)

    assert result["pagination"]["total"] == 57
    assert len(result["rooms"]) == 1
