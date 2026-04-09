"""
SQLAlchemy ORM models for the AI Interviewer database.

Tables:
  - users: authenticated users (via Google OAuth)
  - interviews: interview sessions with questions, answers, and metadata
  - reports: generated interview reports with scoring data
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, DateTime, ForeignKey, Index, JSON, Numeric, String, Text, Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship

# Use JSON base type with JSONB variant for PostgreSQL.
# This lets SQLite work in tests while production uses native JSONB.
JsonColumn = JSON().with_variant(JSONB(), "postgresql")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    email = Column(String(320), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    interviews = relationship("Interview", back_populates="user", lazy="selectin")


class Interview(Base):
    __tablename__ = "interviews"

    id = Column(String(24), primary_key=True)
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=False)
    job_title = Column(String(200), nullable=False)
    candidate_name = Column(String(200), nullable=False)
    candidate_email = Column(String(320), nullable=False)
    domain_knowledge = Column(JsonColumn, nullable=False)
    questions = Column(JsonColumn, nullable=False)
    candidate_info = Column(JsonColumn, nullable=False)
    avatar_id = Column(String(200), nullable=True)
    status = Column(String(20), nullable=False, default="created")
    answers = Column(JsonColumn, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_interviews_user_id_created_at", "user_id", created_at.desc()),
    )

    user = relationship("User", back_populates="interviews")
    report = relationship("Report", back_populates="interview", uselist=False, lazy="selectin")


class Report(Base):
    __tablename__ = "reports"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    interview_id = Column(String(24), ForeignKey("interviews.id"), unique=True, nullable=False)
    report_data = Column(JsonColumn, nullable=False)
    report_text = Column(Text, nullable=True)
    overall_score = Column(Numeric(4, 2), nullable=True)
    recommendation = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    interview = relationship("Interview", back_populates="report")
