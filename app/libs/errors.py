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
        rv["status"] = "error"
        rv["code"] = self.status_code
        return rv


class AuthError(APIError):
    """Authentication/authorization errors"""

    def __init__(self, message="Unauthorized", status_code=401):
        super().__init__(message, status_code)


class UnverifiedEmailError(APIError):
    """Raised when a user attempts to authenticate with an unverified email"""

    def __init__(self, message="Email not verified", status_code=403, payload=None):
        default_payload = {"error_type": "unverified_email"}
        if payload:
            default_payload.update(payload)
        super().__init__(message, status_code, default_payload)


class ForbiddenError(APIError):
    """Forbidden access errors"""

    def __init__(self, message="Forbidden", status_code=403):
        super().__init__(message, status_code)


class NotFoundError(APIError):
    """Resource not found errors"""

    def __init__(self, message="Resource not found", status_code=404):
        super().__init__(message, status_code)


class ValidationError(APIError):
    """Data validation errors"""

    def __init__(self, message="Validation error", status_code=422, errors=None):
        super().__init__(message, status_code)
        self.errors = errors or {}

    def to_dict(self):
        rv = super().to_dict()
        rv["errors"] = self.errors
        return rv


class ConflictError(APIError):
    """Resource conflict errors"""

    def __init__(self, message="Conflict", status_code=409):
        super().__init__(message, status_code)
