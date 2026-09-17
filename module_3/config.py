"""
config.py - Database connection settings for Module 3.

The connection string is read from the DATABASE_URL environment variable
(optionally provided through a local, git-ignored .env file).  Nothing
secret is stored in the repository; see .env.example and README.md.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the module_3 folder if present (does not override real env vars).
load_dotenv(Path(__file__).resolve().parent / ".env")

# Default assumes a local PostgreSQL with a database named "gradcafe" that
# trusts the current user (typical Homebrew / Postgres.app setup).
DEFAULT_DATABASE_URL = "postgresql://localhost:5432/gradcafe"


def get_database_url(driver: str | None = None) -> str:
    """Return the connection URL, optionally rewritten for a SQLAlchemy driver.

    psycopg accepts ``postgresql://...`` directly; SQLAlchemy needs the
    dialect+driver form ``postgresql+psycopg://...`` to use psycopg 3.
    """
    url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    if driver and url.startswith("postgresql://"):
        url = url.replace("postgresql://", f"postgresql+{driver}://", 1)
    return url
