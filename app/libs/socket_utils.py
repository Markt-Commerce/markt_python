"""
Centralized room management utilities for WebSocket namespaces
"""


class RoomManager:
    """Centralized room management for consistent room naming"""

    @staticmethod
    def get_user_room(user_id: str) -> str:
        """Get user-specific room name"""
        return f"user_{user_id}"

    @staticmethod
    def get_post_room(post_id: str) -> str:
        """Get post-specific room name"""
        return f"post_{post_id}"

    @staticmethod
    def get_comment_room(comment_id: int) -> str:
        """Get comment-specific room name"""
        return f"comment_{comment_id}"

    @staticmethod
    def get_message_room(message_id: int) -> str:
        """Get message-specific room name"""
        return f"message_{message_id}"

    @staticmethod
    def get_chat_room(room_id: int) -> str:
        """Get chat room name"""
        return f"room_{room_id}"

    @staticmethod
    def get_order_room(order_id: int) -> str:
        """Get order-specific room name"""
        return f"order_{order_id}"

    @staticmethod
    def get_product_room(product_id: int) -> str:
        """Get product-specific room name"""
        return f"product_{product_id}"

    @staticmethod
    def get_buyer_room(buyer_id: int) -> str:
        """Get buyer-specific room name"""
        return f"buyer_{buyer_id}"

    @staticmethod
    def get_seller_room(seller_id: int) -> str:
        """Get seller-specific room name"""
        return f"seller_{seller_id}"

    @staticmethod
    def get_seller_orders_room(seller_id: int) -> str:
        """Get seller orders room name"""
        return f"seller_orders_{seller_id}"


class EventManager:
    """Centralized event management for consistent event naming and data structure"""

    @staticmethod
    def create_event_data(event: str, data: dict, version: str = "1.0") -> dict:
        """Create standardized event data structure"""
        return {
            "version": version,
            "event": event,
            "data": data,
            "timestamp": datetime.utcnow().isoformat(),
        }

    @staticmethod
    def create_error_response(message: str, code: str = "GENERIC_ERROR") -> dict:
        """Create standardized error response"""
        return {
            "success": False,
            "error": {
                "message": message,
                "code": code,
                "timestamp": datetime.utcnow().isoformat(),
            },
        }

    @staticmethod
    def create_success_response(data: dict = None) -> dict:
        """Create standardized success response"""
        return {
            "success": True,
            "data": data,
            "timestamp": datetime.utcnow().isoformat(),
        }

    @staticmethod
    def create_acknowledgment(event_id: str, success: bool, error: str = None) -> dict:
        """Create event acknowledgment response"""
        ack = {
            "event_id": event_id,
            "success": success,
            "timestamp": datetime.utcnow().isoformat(),
        }
        if error:
            ack["error"] = error
        return ack


# Import datetime for the EventManager
from datetime import datetime
