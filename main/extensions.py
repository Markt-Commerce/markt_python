from flask_socketio import SocketIO

# Initialize without app
socketio = SocketIO(
    cors_allowed_origins="*",
    async_mode="gevent",
    logger=False,
    engineio_logger=False,
    manage_session=False,
)
