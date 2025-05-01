from main.setup import create_app
from main.config import settings
import logging

app, socketio = create_app()

if __name__ == "__main__":
    host, port = settings.BIND.split(":")
    logging.info(f"Starting Markt server on {host}:{port}")

    socketio.run(
        app,
        host=host,
        port=int(port),
        debug=settings.DEBUG,
        use_reloader=True,
        log_output=settings.DEBUG,
    )
