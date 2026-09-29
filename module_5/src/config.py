"""
config.py - Database connection settings.

Credentials are never written in code.  The connection is described by
environment variables (optionally provided through a local, git-ignored
``.env`` file next to this module - see ``.env.example``):

``DB_HOST``, ``DB_PORT``, ``DB_NAME``, ``DB_USER``, ``DB_PASSWORD``
    Assembled into ``postgresql://user:password@host:port/name``.
``DATABASE_URL``
    Optional full URL that overrides the five variables above (handy for CI
    and tests, which point it at a throwaway database).
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

# Load .env from the module folder if present (never overrides real env vars).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(Path(__file__).resolve().parent / ".env")

DEFAULTS = {"DB_HOST": "localhost", "DB_PORT": "5432", "DB_NAME": "gradcafe", "DB_USER": "", "DB_PASSWORD": ""}


def database_settings() -> dict:
    """The DB_* values currently in effect (environment first, then defaults)."""
    return {key: os.getenv(key, default) for key, default in DEFAULTS.items()}


def get_database_url() -> str:
    """Return the PostgreSQL connection URL built from the environment.

    ``DATABASE_URL`` wins when set; otherwise the URL is assembled from the
    ``DB_*`` variables with the user/password percent-encoded so special
    characters in a password cannot corrupt the URL.
    """
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit
    cfg = database_settings()
    auth = ""
    if cfg["DB_USER"]:
        auth = quote(cfg["DB_USER"], safe="")
        if cfg["DB_PASSWORD"]:
            auth += ":" + quote(cfg["DB_PASSWORD"], safe="")
        auth += "@"
    return f"postgresql://{auth}{cfg['DB_HOST']}:{cfg['DB_PORT']}/{cfg['DB_NAME']}"
