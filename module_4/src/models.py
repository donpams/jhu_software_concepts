"""
models.py - SQLAlchemy 2.x ORM mapping for the ``applicants`` table.

The model maps onto the *existing* table created by load_data.py (same
PostgreSQL database, same rows) - no second copy of the data is created.
``Base.metadata.create_all`` is intentionally not called anywhere; the schema
is owned by load_data.py.

Exports
-------

``Applicant``
    Declarative model, one instance per row, ``p_id`` primary key.
``configure_engine``
    (Re)build the Engine/sessionmaker for a given URL; tests call it with
    their own ``DATABASE_URL``.
``get_engine``
    The current Engine (built lazily from ``DATABASE_URL``).
``get_session``
    Context-manager helper: ``with get_session() as session: ...``.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from typing import Iterator, Optional

from sqlalchemy import Date, Engine, Float, Integer, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from config import get_database_url


class Base(DeclarativeBase):
    """Declarative base shared by all models (there is only one here)."""


class Applicant(Base):
    """One Grad Cafe submission (a row of the ``applicants`` table)."""

    __tablename__ = "applicants"

    p_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    program: Mapped[Optional[str]] = mapped_column(Text)
    comments: Mapped[Optional[str]] = mapped_column(Text)
    date_added: Mapped[Optional[date]] = mapped_column(Date)
    url: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    status: Mapped[Optional[str]] = mapped_column(Text)
    term: Mapped[Optional[str]] = mapped_column(Text)
    us_or_international: Mapped[Optional[str]] = mapped_column(Text)
    gpa: Mapped[Optional[float]] = mapped_column(Float)
    gre: Mapped[Optional[float]] = mapped_column(Float)
    gre_v: Mapped[Optional[float]] = mapped_column(Float)
    gre_aw: Mapped[Optional[float]] = mapped_column(Float)
    degree: Mapped[Optional[str]] = mapped_column(Text)
    llm_generated_program: Mapped[Optional[str]] = mapped_column(Text)
    llm_generated_university: Mapped[Optional[str]] = mapped_column(Text)

    def __repr__(self) -> str:
        return (f"Applicant(p_id={self.p_id}, program={self.program!r}, "
                f"status={self.status!r}, term={self.term!r})")


# --------------------------------------------------------------------------- #
# Engine + Session (modern SQLAlchemy 2.x conventions)                        #
# --------------------------------------------------------------------------- #
_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker] = None


def configure_engine(database_url: Optional[str] = None) -> Engine:
    """Build (or rebuild) the Engine and sessionmaker for ``database_url``.

    ``database_url`` defaults to ``DATABASE_URL``; the plain ``postgresql://``
    form is rewritten to ``postgresql+psycopg://`` so SQLAlchemy uses psycopg 3.
    """
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    url = database_url or get_database_url()
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    _engine = create_engine(url, pool_pre_ping=True, future=True)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    """The current Engine, created on first use from ``DATABASE_URL``."""
    if _engine is None:
        configure_engine()
    return _engine  # type: ignore[return-value]


@contextmanager
def get_session() -> Iterator[Session]:
    """Yield a Session bound to the current engine and always close it."""
    get_engine()
    session = _session_factory()  # type: ignore[misc]
    try:
        yield session
    finally:
        session.close()
