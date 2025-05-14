from flask import jsonify
from werkzeug.exceptions import HTTPException
import logging
from app.libs.errors import APIError

logger = logging.getLogger(__name__)


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
