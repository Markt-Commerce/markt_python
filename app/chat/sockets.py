from flask_socketio import Namespace, emit
from flask_login import current_user


class ChatNamespace(Namespace):
    def on_connect(self):
        if current_user.is_authenticated:
            emit("status", {"message": "Connected"})
        else:
            return False  # Reject connection

    def on_join(self, data):
        room = data["room_id"]
        self.join_room(room)
        emit(
            "message",
            {"user": current_user.username, "msg": "joined the room"},
            room=room,
        )

    def on_message(self, data):
        room = data["room_id"]
        emit(
            "message",
            {
                "user": current_user.username,
                "msg": data["message"],
                "product": data.get("product_id"),
            },
            room=room,
        )
