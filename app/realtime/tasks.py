"""
Real-time event tasks for async socket emissions
This module handles socket events asynchronously to decouple them from API responses
"""
import logging
from datetime import datetime
from celery import current_task
from main.extensions import socketio
from external.redis import redis_client
from main.workers import celery_app
from app.realtime.throttler import redis_event_throttler

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, queue="realtime")
def emit_post_liked_task(
    self, post_id: str, user_id: str, username: str, like_count: int = None
):
    """Emit post liked event asynchronously with throttling"""
    try:
        event_data = {
            "post_id": post_id,
            "user_id": user_id,
            "username": username,
            "timestamp": datetime.utcnow().isoformat(),
        }

        if like_count is not None:
            event_data["like_count"] = like_count

        # Emit to post room with throttling
        room = f"post_{post_id}"

        # Use throttler to prevent spam (1 second interval for likes)
        throttled = redis_event_throttler.throttle_emit(
            "post_liked", event_data, room, custom_interval=1.0
        )

        if throttled:
            logger.info(
                f"Emitted post_liked event for post {post_id} by user {user_id}"
            )
        else:
            logger.debug(
                f"Throttled post_liked event for post {post_id} by user {user_id}"
            )

        return True

    except Exception as e:
        logger.error(f"Failed to emit post_liked event: {e}")
        return False


@celery_app.task(bind=True, queue="realtime")
def emit_post_unliked_task(
    self, post_id: str, user_id: str, username: str, like_count: int = None
):
    """Emit post unliked event asynchronously with throttling"""
    try:
        event_data = {
            "post_id": post_id,
            "user_id": user_id,
            "username": username,
            "timestamp": datetime.utcnow().isoformat(),
        }

        if like_count is not None:
            event_data["like_count"] = like_count

        # Emit to post room with throttling
        room = f"post_{post_id}"

        # Use throttler to prevent spam (1 second interval for unlikes)
        throttled = redis_event_throttler.throttle_emit(
            "post_unliked", event_data, room, custom_interval=1.0
        )

        if throttled:
            logger.info(
                f"Emitted post_unliked event for post {post_id} by user {user_id}"
            )
        else:
            logger.debug(
                f"Throttled post_unliked event for post {post_id} by user {user_id}"
            )

        return True

    except Exception as e:
        logger.error(f"Failed to emit post_unliked event: {e}")
        return False


@celery_app.task(bind=True, queue="realtime")
def emit_comment_reaction_added_task(
    self, comment_id: int, user_id: str, username: str, reaction_type: str
):
    """Emit comment reaction added event asynchronously with throttling"""
    try:
        event_data = {
            "comment_id": comment_id,
            "user_id": user_id,
            "username": username,
            "reaction_type": reaction_type,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Emit to comment room with throttling
        room = f"comment_{comment_id}"

        # Use throttler to prevent spam (0.5 second interval for reactions)
        throttled = redis_event_throttler.throttle_emit(
            "comment_reaction_added", event_data, room, custom_interval=0.5
        )

        if throttled:
            logger.info(
                f"Emitted comment_reaction_added event for comment {comment_id} by user {user_id}"
            )
        else:
            logger.debug(
                f"Throttled comment_reaction_added event for comment {comment_id} by user {user_id}"
            )

        return True

    except Exception as e:
        logger.error(f"Failed to emit comment_reaction_added event: {e}")
        return False


@celery_app.task(bind=True, queue="realtime")
def emit_comment_reaction_removed_task(
    self, comment_id: int, user_id: str, username: str, reaction_type: str
):
    """Emit comment reaction removed event asynchronously with throttling"""
    try:
        event_data = {
            "comment_id": comment_id,
            "user_id": user_id,
            "username": username,
            "reaction_type": reaction_type,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Emit to comment room with throttling
        room = f"comment_{comment_id}"

        # Use throttler to prevent spam (0.5 second interval for reactions)
        throttled = redis_event_throttler.throttle_emit(
            "comment_reaction_removed", event_data, room, custom_interval=0.5
        )

        if throttled:
            logger.info(
                f"Emitted comment_reaction_removed event for comment {comment_id} by user {user_id}"
            )
        return True

    except Exception as e:
        logger.error(f"Failed to emit comment_reaction_removed event: {e}")
        return False


@celery_app.task(bind=True, queue="realtime")
def emit_buyer_request_upvoted_task(
    self, request_id: str, user_id: str, username: str, upvote_count: int = None
):
    """Emit buyer request upvoted event asynchronously with throttling"""
    try:
        event_data = {
            "request_id": request_id,
            "user_id": user_id,
            "username": username,
            "timestamp": datetime.utcnow().isoformat(),
        }

        if upvote_count is not None:
            event_data["upvote_count"] = upvote_count

        # Emit to request room with throttling
        room = f"request_{request_id}"

        # Use throttler to prevent spam (2 second interval for upvotes)
        throttled = redis_event_throttler.throttle_emit(
            "request_upvoted", event_data, room, custom_interval=2.0
        )

        if throttled:
            logger.info(
                f"Emitted request_upvoted event for request {request_id} by user {user_id}"
            )
        else:
            logger.debug(
                f"Throttled request_upvoted event for request {request_id} by user {user_id}"
            )

        return True

    except Exception as e:
        logger.error(f"Failed to emit request_upvoted event: {e}")
        return False


@celery_app.task(bind=True, queue="realtime")
def emit_order_status_changed_task(
    self, order_id: str, user_id: str, status: str, metadata: dict = None
):
    """Emit order status change event asynchronously"""
    try:
        event_data = {
            "order_id": order_id,
            "user_id": user_id,
            "status": status,
            "timestamp": datetime.utcnow().isoformat(),
        }

        if metadata:
            event_data.update(metadata)

        # Emit to order room
        room = f"order_{order_id}"
        socketio.emit(
            "order_status_changed", event_data, room=room, namespace="/orders"
        )

        logger.info(f"Emitted order_status_changed event for order {order_id}")
        return True

    except Exception as e:
        logger.error(f"Failed to emit order_status_changed event: {e}")
        return False


@celery_app.task(bind=True, queue="realtime")
def emit_chat_message_task(self, room_id: str, message_data: dict):
    """Emit chat message event asynchronously"""
    try:
        # Emit to chat room
        room = f"chat_{room_id}"
        socketio.emit("new_message", message_data, room=room, namespace="/chat")

        logger.info(f"Emitted new_message event for chat room {room_id}")
        return True

    except Exception as e:
        logger.error(f"Failed to emit new_message event: {e}")
        return False


@celery_app.task(bind=True, queue="realtime")
def emit_review_added_task(self, product_id: str, review_data: dict):
    """Emit review added event asynchronously with throttling"""
    try:
        # Emit to product room with throttling
        room = f"product_{product_id}"

        # Use throttler to prevent spam (1 second interval for reviews)
        throttled = redis_event_throttler.throttle_emit(
            "review_added", review_data, room, custom_interval=1.0
        )

        if throttled:
            logger.info(f"Emitted review_added event for product {product_id}")
        else:
            logger.debug(f"Throttled review_added event for product {product_id}")

        return True

    except Exception as e:
        logger.error(f"Failed to emit review_added event: {e}")
        return False


@celery_app.task(bind=True, queue="realtime")
def emit_review_upvoted_task(self, product_id: str, review_data: dict):
    """Emit review upvoted event asynchronously with throttling"""
    try:
        # Emit to product room with throttling
        room = f"product_{product_id}"

        # Use throttler to prevent spam (1 second interval for review upvotes)
        throttled = redis_event_throttler.throttle_emit(
            "review_upvoted", review_data, room, custom_interval=1.0
        )

        if throttled:
            logger.info(f"Emitted review_upvoted event for product {product_id}")
        else:
            logger.debug(f"Throttled review_upvoted event for product {product_id}")

        return True

    except Exception as e:
        logger.error(f"Failed to emit review_upvoted event: {e}")
        return False


# Convenience functions for the EventManager
def emit_post_liked(post_id: str, user_id: str, username: str, like_count: int = None):
    """Queue post liked event"""
    return emit_post_liked_task.delay(post_id, user_id, username, like_count)


def emit_post_unliked(
    post_id: str, user_id: str, username: str, like_count: int = None
):
    """Queue post unliked event"""
    return emit_post_unliked_task.delay(post_id, user_id, username, like_count)


def emit_comment_reaction_added(
    comment_id: int, user_id: str, username: str, reaction_type: str
):
    """Queue comment reaction added event"""
    return emit_comment_reaction_added_task.delay(
        comment_id, user_id, username, reaction_type
    )


def emit_comment_reaction_removed(
    comment_id: int, user_id: str, username: str, reaction_type: str
):
    """Queue comment reaction removed event"""
    return emit_comment_reaction_removed_task.delay(
        comment_id, user_id, username, reaction_type
    )


def emit_buyer_request_upvoted(
    request_id: str, user_id: str, username: str, upvote_count: int = None
):
    """Queue buyer request upvoted event"""
    return emit_buyer_request_upvoted_task.delay(
        request_id, user_id, username, upvote_count
    )


def emit_order_status_changed(
    order_id: str, user_id: str, status: str, metadata: dict = None
):
    """Queue order status changed event"""
    return emit_order_status_changed_task.delay(order_id, user_id, status, metadata)


def emit_chat_message(room_id: str, message_data: dict):
    """Queue chat message event"""
    return emit_chat_message_task.delay(room_id, message_data)


def emit_review_added(product_id: str, review_data: dict):
    """Queue review added event"""
    return emit_review_added_task.delay(product_id, review_data)


def emit_review_upvoted(product_id: str, review_data: dict):
    """Queue review upvoted event"""
    return emit_review_upvoted_task.delay(product_id, review_data)
