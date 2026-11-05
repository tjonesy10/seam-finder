"""JSON values: ISO 8601 dates, timestamps with offset, numerics as numbers."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID


class JsonNumber(float):
    """JSON number whose text is the Decimal's, not a binary float's."""

    def __new__(cls, value: Decimal):
        number = super().__new__(cls, float(value))
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        number._text = text or "0"
        return number

    def __repr__(self) -> str:
        return self._text


def to_jsonable(value):
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Decimal):
        return JsonNumber(value)
    if isinstance(value, float):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return str(value)
