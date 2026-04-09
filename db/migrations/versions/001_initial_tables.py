"""Create users, interviews, and reports tables.

Revision ID: 001
Revises: None
Create Date: 2026-04-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(320), unique=True, nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "interviews",
        sa.Column("id", sa.String(24), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("job_title", sa.String(200), nullable=False),
        sa.Column("candidate_name", sa.String(200), nullable=False),
        sa.Column("candidate_email", sa.String(320), nullable=False),
        sa.Column("domain_knowledge", JSONB, nullable=False),
        sa.Column("questions", JSONB, nullable=False),
        sa.Column("candidate_info", JSONB, nullable=False),
        sa.Column("avatar_id", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="created"),
        sa.Column("answers", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_interviews_user_id_created_at",
        "interviews",
        ["user_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("interview_id", sa.String(24), sa.ForeignKey("interviews.id"), unique=True, nullable=False),
        sa.Column("report_data", JSONB, nullable=False),
        sa.Column("report_text", sa.Text, nullable=True),
        sa.Column("overall_score", sa.Numeric(4, 2), nullable=True),
        sa.Column("recommendation", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("reports")
    op.drop_index("ix_interviews_user_id_created_at", table_name="interviews")
    op.drop_table("interviews")
    op.drop_table("users")
