"""
models.py - SQLAlchemy 2.x ORM mapping for the ``applicants`` table.

The model maps onto the *existing* table created by load_data.py (same
PostgreSQL database, same rows) - no second copy of the data is created.
``Base.metadata.create_all`` is intentionally not called anywhere; the schema
is owned by load_data.py.

Exports
-------
Applicant   - declarative model, one instance per row, ``p_id`` primary key
engine      - SQLAlchemy Engine built from DATABASE_URL (psycopg 3 driver)
SessionLocal- sessionmaker bound to that engine
get_session - context-manager helper: ``with get_session() as session: ...``
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from typing import Iterator, Optional

from sqlalchemy import Date, Float, Integer, Text, create_engine
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

    def __repr__(self) -> str:  # helpful in the REPL / debugging
        return (f"Applicant(p_id={self.p_id}, program={self.program!r}, "
                f"status={self.status!r}, term={self.term!r})")


# --------------------------------------------------------------------------- #
# Engine + Session (modern SQLAlchemy 2.x conventions)                        #
# --------------------------------------------------------------------------- #
engine = create_engine(get_database_url(driver="psycopg"), pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def get_session() -> Iterator[Session]:
    """Yield a Session and always close it (read-only use in this project)."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
