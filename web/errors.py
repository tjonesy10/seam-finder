"""Error shape shared by the JSON API and the HTML pages."""

from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str, param: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.param = param


def is_db_unavailable(exc: BaseException) -> bool:
    if isinstance(exc, (OperationalError, InterfaceError)):
        return True
    return isinstance(exc, DBAPIError) and bool(getattr(exc, "connection_invalidated", False))


def error_body(exc: AppError) -> dict:
    error = {"code": exc.code, "message": exc.message}
    if exc.param is not None:
        error["param"] = exc.param
    return {"error": error}
