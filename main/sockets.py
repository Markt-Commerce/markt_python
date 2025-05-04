from app.chats.sockets import ChatNamespace


def register_socket_namespaces(socketio):
    """Register socket namespaces
    Make dynamic in later phases
    """
    socketio.on_namespace(ChatNamespace("/chat"))
