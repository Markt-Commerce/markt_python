from app.chats.sockets import ChatNamespace
from app.socials.sockets import SocialNamespace
from app.notifications.sockets import NotificationNamespace


def register_socket_namespaces(socketio):
    """Register socket namespaces
    Make dynamic in later phases
    """
    socketio.on_namespace(ChatNamespace("/chat"))
    socketio.on_namespace(SocialNamespace("/social"))
    socketio.on_namespace(NotificationNamespace("/notification"))
