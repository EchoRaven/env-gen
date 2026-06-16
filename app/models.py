"""Registry tables — the persistent record of every environment the generator
has produced (and is producing). Per-env hub state is NOT stored here; it is read
live from the generated tree by ``hub_reader``."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Environment(Base):
    __tablename__ = "environments"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # slug == generated dir name
    name: Mapped[str] = mapped_column(String, nullable=False)
    # multi-tenancy: each environment is owned by the tenant/user that created it
    tenant_id: Mapped[str] = mapped_column(String, default="", index=True)
    created_by: Mapped[str] = mapped_column(String, default="")
    reference: Mapped[str] = mapped_column(String, default="")
    model: Mapped[str] = mapped_column(String, default="")
    provider: Mapped[str] = mapped_column(String, default="")
    scope: Mapped[str] = mapped_column(String, default="")
    requirements: Mapped[str] = mapped_column(String, default="")
    max_wallclock_min: Mapped[int] = mapped_column(Integer, default=120)
    max_ticks: Mapped[int] = mapped_column(Integer, default=240)
    gates_json: Mapped[str] = mapped_column(String, default="[]")
    status: Mapped[str] = mapped_column(String, default="generating")
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    generated_dir: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class Run(Base):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    env_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String, default="generating")
    milestone: Mapped[str | None] = mapped_column(String, nullable=True)
    coordination_ticks: Mapped[int] = mapped_column(Integer, default=0)
    wallclock_sec: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    env_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    thread_id: Mapped[str] = mapped_column(String, index=True, default="main")
    sender: Mapped[str] = mapped_column(String, default="user")     # "user" or an agent id
    recipients: Mapped[str] = mapped_column(String, default="")     # csv of agent ids
    content: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
