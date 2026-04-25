"""Add resumes table and resume-based interview columns.

Revision ID: 004
Revises: 003
Create Date: 2026-04-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "resumes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False, server_default="application/pdf"),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("file_data", sa.LargeBinary(), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_resumes_user_id", "resumes", ["user_id"])

    op.add_column(
        "interviews",
        sa.Column("interview_type", sa.String(20), nullable=False, server_default="job_description"),
    )
    op.add_column("interviews", sa.Column("target_field", sa.String(100), nullable=True))
    op.add_column(
        "interviews",
        sa.Column("resume_id", UUID(as_uuid=True), sa.ForeignKey("resumes.id"), nullable=True),
    )
    op.create_index("ix_interviews_resume_id", "interviews", ["resume_id"])


def downgrade() -> None:
    op.drop_index("ix_interviews_resume_id", table_name="interviews")
    op.drop_column("interviews", "resume_id")
    op.drop_column("interviews", "target_field")
    op.drop_column("interviews", "interview_type")
    op.drop_index("ix_resumes_user_id", table_name="resumes")
    op.drop_table("resumes")
