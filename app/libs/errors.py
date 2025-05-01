class APIError(Exception):
    """Base API error with status code and message"""

    def __init__(self, message, status_code=400, payload=None):
        super().__init__()
        self.message = message
        self.status_code = status_code
        self.payload = payload

    def to_dict(self):
        rv = dict(self.payload or ())
        rv["message"] = self.message
        return rv


class AuthError(APIError):
    """Authentication/authorization errors"""

    def __init__(self, message, status_code=401):
        super().__init__(message, status_code)


class NotFoundError(APIError):
    """Resource not found errors"""

    def __init__(self, message="Resource not found", status_code=404):
        super().__init__(message, status_code)
