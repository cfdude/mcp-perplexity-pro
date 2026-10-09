"""ORM models for the tables the server owns (the schema itself is built by migrations)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Project(Base):
    """A named group of stored records. ``created_at`` is UTC (SQLite stores it naive)."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UsageEvent(Base):
    """One costed upstream call (usage-recording spec; design D1).

    A RETAINED table (local-storage "Retained records"): ``project_id`` is ``ON DELETE SET NULL``
    and ``project_name`` keeps the name as written, so spend history survives project deletion
    and stays reportable by name. ``created_at`` is naive UTC with microseconds, written by the
    recorder. Money is an integer count of nano-USD (10^-9 USD). The schema itself is built by
    migration ``0002``; this model must match it (a test compares the two).
    """

    __tablename__ = "usage_events"
    __table_args__ = (
        Index("ix_usage_events_created_at", "created_at"),
        Index("ix_usage_events_project_name", "project_name"),
        # one stored event per successful upstream response (design D8)
        Index(
            "uq_usage_events_api_request_id",
            "api",
            "request_id",
            unique=True,
            sqlite_where=text("request_id IS NOT NULL AND status = 'ok'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime())
    tool: Mapped[str] = mapped_column(String())
    api: Mapped[str] = mapped_column(String())
    status: Mapped[str] = mapped_column(String())
    latency_ms: Mapped[int | None] = mapped_column(Integer())
    model: Mapped[str | None] = mapped_column(String())
    preset: Mapped[str | None] = mapped_column(String())
    request_id: Mapped[str | None] = mapped_column(String())
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    project_name: Mapped[str | None] = mapped_column(String())
    input_tokens: Mapped[int | None] = mapped_column(Integer())
    output_tokens: Mapped[int | None] = mapped_column(Integer())
    total_tokens: Mapped[int | None] = mapped_column(Integer())
    cached_tokens: Mapped[int | None] = mapped_column(Integer())
    cache_creation_tokens: Mapped[int | None] = mapped_column(Integer())
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer())
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer())
    cost_nano_usd: Mapped[int] = mapped_column(Integer(), server_default=text("0"))
    cost_source: Mapped[str] = mapped_column(String())  # reported | computed | none
    currency: Mapped[str] = mapped_column(String(), server_default=text("'USD'"))
    input_cost_nano: Mapped[int | None] = mapped_column(Integer())
    output_cost_nano: Mapped[int | None] = mapped_column(Integer())
    cache_read_cost_nano: Mapped[int | None] = mapped_column(Integer())
    cache_creation_cost_nano: Mapped[int | None] = mapped_column(Integer())
    tool_calls_cost_nano: Mapped[int | None] = mapped_column(Integer())
    price_table: Mapped[str | None] = mapped_column(String())
    tool_calls_json: Mapped[str | None] = mapped_column(Text())
    usage_json: Mapped[str | None] = mapped_column(Text())
