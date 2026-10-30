"""A message sent over HTTP is pushed to the room, like a socket send.

Only the Socket.IO handler used to emit; a REST-sent message (seller tools,
the app's fallback when its socket is down) was saved but never delivered
live -- the other person saw it only after reloading the thread.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from app.chats.services import ChatService


def _message():
    return SimpleNamespace(
        id=42,
        room_id=7,
        sender_id="USR_S",
        content="Yes o! In stock.",
        message_type="text",
        message_data=None,
        is_read=False,
        created_at=datetime(2026, 10, 27, 9, 41),
    )


def test_rest_message_is_emitted_to_the_room():
    with patch("main.extensions.socketio.emit") as emit:
        ChatService.broadcast_message(_message(), "adasankara")
    emit.assert_called_once()
    event, payload = emit.call_args.args
    assert event == "message"
    assert payload["id"] == 42 and payload["sender_username"] == "adasankara"
    assert payload["created_at"] == "2026-10-27T09:41:00"
    assert emit.call_args.kwargs == {"room": "room_7", "namespace": "/chat"}


def test_a_failed_emit_does_not_raise():
    with patch("main.extensions.socketio.emit", side_effect=RuntimeError("down")):
        ChatService.broadcast_message(_message())  # message is already saved
