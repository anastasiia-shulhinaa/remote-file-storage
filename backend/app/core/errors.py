"""Application errors raised by services and mapped to HTTP status codes in main.py.

Every error carries a stable machine-readable `code`. Clients translate the code
into a user-facing message; `detail` is a technical English text and never contains
raw exception output from Supabase or other libraries.
"""


class AppError(Exception):
    status_code = 500
    default_code = "internal_error"

    def __init__(self, detail: str = "Internal server error", code: str | None = None, extra: dict | None = None):
        super().__init__(detail)
        self.detail = detail
        self.code = code or self.default_code
        # additional machine-readable fields for the response (e.g. the id of a blocking sync)
        self.extra = extra or {}


class BadRequestError(AppError):
    status_code = 400
    default_code = "bad_request"


class UnauthorizedError(AppError):
    status_code = 401
    default_code = "unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    default_code = "forbidden"


class NotFoundError(AppError):
    status_code = 404
    default_code = "not_found"


class ConflictError(AppError):
    status_code = 409
    default_code = "conflict"


class ValidationError(AppError):
    status_code = 422
    default_code = "validation_error"


class StorageError(AppError):
    status_code = 502
    default_code = "storage_error"


class ServiceUnavailableError(AppError):
    status_code = 503
    default_code = "service_unavailable"
