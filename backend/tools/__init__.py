"""Tool package: agent-facing tools plus helpers for JSON-serializable results."""

from datetime import date, datetime


def jsonable(value):
    # psycopg returns tz-aware datetimes; tool results must stay JSON-serializable.
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def jsonable_row(row: dict) -> dict:
    return {k: jsonable(v) for k, v in row.items()}
