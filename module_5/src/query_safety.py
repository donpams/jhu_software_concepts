"""
query_safety.py - Shared guards for every SQL statement in the project.

Two rules apply to all database access in ``module_5/src``:

1. **Every statement carries a LIMIT** and the value is clamped to
   ``1 <= limit <= MAX_LIMIT`` by :func:`clamp_limit`, so a caller (or an
   HTTP client) can never ask for an unbounded result set.
2. **Dynamic SQL parts are never string-formatted.**  Column names that come
   from a caller pass through :func:`safe_column`, which checks them against
   the table's real column list and returns a quoted :class:`psycopg.sql.Identifier`;
   values are always bound as parameters (``%s`` / ``sql.Placeholder``).
"""

from __future__ import annotations

from typing import Any, Optional

from psycopg import sql

MAX_LIMIT = 100
DEFAULT_LIMIT = 20
TABLE = "applicants"

# The only columns a caller may name (order-by, filter).  Anything else is rejected.
ALLOWED_COLUMNS = (
    "p_id", "program", "comments", "date_added", "url", "status", "term",
    "us_or_international", "gpa", "gre", "gre_v", "gre_aw", "degree",
    "llm_generated_program", "llm_generated_university",
)


def clamp_limit(value: Any, default: int = DEFAULT_LIMIT) -> int:
    """Turn any caller-supplied limit into an int within ``[1, MAX_LIMIT]``.

    ``None``, blanks and non-numeric strings fall back to ``default``; values
    below 1 become 1; values above ``MAX_LIMIT`` become ``MAX_LIMIT``.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(1, min(number, MAX_LIMIT))


def safe_column(name: Optional[str], default: str = "date_added") -> sql.Identifier:
    """Return a quoted Identifier for ``name`` if it is a real column, else raise ValueError."""
    column = (name or default).strip()
    if column not in ALLOWED_COLUMNS:
        raise ValueError(f"unknown column {column!r}")
    return sql.Identifier(column)


def table_identifier() -> sql.Identifier:
    """The applicants table as a quoted Identifier."""
    return sql.Identifier(TABLE)
