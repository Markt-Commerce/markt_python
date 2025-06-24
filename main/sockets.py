from flask_socketio import emit, disconnect
from app.chats.sockets import ChatNamespace
from app.socials.sockets import SocialNamespace
from app.notifications.sockets import NotificationNamespace
from app.orders.sockets import OrderNamespace


def register_socket_namespaces(socketio):
    """Register socket namespaces with enhanced architecture

    Architecture Decision:
    - Server-side emissions for critical real-time features
    - Client-side events for non-critical updates
    - Hybrid approach for notifications (immediate + fallback)

    Namespace Structure:
    /chat - Real-time messaging (server-side emissions)
    /social - Social interactions (server-side emissions)
    /notification - Notifications (hybrid approach)
    /orders - Order tracking and payment updates (server-side emissions)
    """

    # Register namespaces with error handling
    try:
        socketio.on_namespace(ChatNamespace("/chat"))
        socketio.on_namespace(SocialNamespace("/social"))
        socketio.on_namespace(NotificationNamespace("/notification"))
        socketio.on_namespace(OrderNamespace("/orders"))

        # Add global error handler for socket connections
        @socketio.on_error()
        def error_handler(e):
            print(f"SocketIO error: {e}")  # noqa: T201

        # Add connection event logging
        @socketio.on("connect")
        def handle_connect():
            print("Client connected")  # noqa: T201

        @socketio.on("disconnect")
        def handle_disconnect():
            print("Client disconnected")  # noqa: T201

    except Exception as e:
        print(f"Error registering socket namespaces: {e}")  # noqa: T201
        raise
