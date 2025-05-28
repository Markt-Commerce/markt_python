import json

from flask_socketio import Namespace, emit
from flask_login import current_user
from external.redis import redis_client


class NotificationNamespace(Namespace):
    def on_connect(self):
        """Authenticate and subscribe to notifications"""
        if not current_user.is_authenticated:
            return emit("error", {"message": "Unauthorized"})

        # Initialize Redis subscription
        self.pubsub = redis_client.pubsub()
        self.pubsub.subscribe(f"notifications:{current_user.id}")

        # Start listening in background
        self.listening = True
        from threading import Thread

        self.thread = Thread(target=self._listen_redis)
        self.thread.start()

    def _listen_redis(self):
        """Listen for Redis messages and emit Socket.IO events"""
        for message in self.pubsub.listen():
            if not self.listening:
                break
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    emit("notification", data, room=self.sid)
                except Exception as e:
                    print(f"Error handling Redis message: {str(e)}") # noqa

    def on_disconnect(self):
        """Clean up Redis subscription"""
        if hasattr(self, "listening"):
            self.listening = False
            if hasattr(self, "pubsub"):
                self.pubsub.unsubscribe()
                self.pubsub.close()
            if hasattr(self, "thread"):
                self.thread.join()
