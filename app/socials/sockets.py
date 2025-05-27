from flask_socketio import Namespace, emit
from flask_login import current_user
from external.redis import redis_client


class SocialNamespace(Namespace):
    def on_connect(self):
        if current_user.is_authenticated:
            self.join_room(f"user_{current_user.id}")
            emit("connected", {"status": "ok"})

    def on_new_post(self, data):
        """Handle new post creation"""
        if not current_user.is_authenticated:
            return

        # Broadcast to followers
        followers = redis_client.smembers(f"user:{current_user.id}:followers")
        for follower_id in followers:
            emit("new_post", data, room=f"user_{follower_id}")

    def on_like_post(self, data):
        """Handle post likes"""
        post_id = data.get("post_id")
        if not post_id or not current_user.is_authenticated:
            return

        # Notify post owner
        post_owner = redis_client.hget(f"post:{post_id}", "owner_id")
        if post_owner and post_owner != current_user.id:
            emit("post_liked", data, room=f"user_{post_owner}")
