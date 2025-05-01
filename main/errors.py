from flask import jsonify
from werkzeug.exceptions import HTTPException
import logging

logger = logging.getLogger(__name__)


class APIError(Exception):
    def __init__(self, message, status_code=400, payload=None):
        super().__init__()
        self.message = message
        self.status_code = status_code
        self.payload = payload

    def to_dict(self):
        rv = dict(self.payload or ())
        rv["message"] = self.message
        return rv


def handle_error(e):
    if isinstance(e, APIError):
        logger.error(f"API Error: {e.message}")
        return jsonify(e.to_dict()), e.status_code
    elif isinstance(e, HTTPException):
        logger.error(f"HTTP Error: {e.description}")
        return jsonify({"message": e.description}), e.code
    else:
        logger.exception("Unhandled exception")
        return jsonify({"message": "Internal server error"}), 500
