#!/usr/bin/env python3
"""
Flask-SocketIO Server with proper gevent monkey patching.
This ensures gevent monkey patching is applied before ANY imports,
preventing SSL recursion errors when using Redis with Flask-SocketIO.
"""

# IMPORTANT: Apply gevent monkey patching FIRST, before any other imports
from gevent.monkey import patch_all
patch_all()

# Now it's safe to import everything else
from main.setup import create_app
from main.config import settings
import logging

if __name__ == "__main__":
    app, socketio = create_app()
    
    host, port = settings.BIND.split(":")
    logging.info(f"Starting Markt server on {host}:{port}")

    socketio.run(
        app,
        host=host,
        port=int(port),
        debug=settings.DEBUG,
        use_reloader=False,  # Disable reloader to avoid import conflicts
        log_output=settings.DEBUG,
    )

