from main.setup import create_app
from main.config import settings
import logging

app = create_app()

if __name__ == "__main__":
    pass

    host, port = settings.BIND.split(":")
    logging.info(f"Starting Markt server on {host}:{port}")
    app.run(host=host, port=int(port), debug=settings.DEBUG)
