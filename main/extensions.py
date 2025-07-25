from flask_socketio import SocketIO
from main.config import settings

# Initialize with Redis message queue for scaling
socketio = SocketIO(
    cors_allowed_origins="*",
    async_mode="gevent",
    logger=False,
    engineio_logger=False,
    manage_session=False,
    message_queue=f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/0"
    if hasattr(settings, "REDIS_HOST")
    else None,
)
