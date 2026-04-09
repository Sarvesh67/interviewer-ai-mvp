"""Lowercase candidate_email on existing interviews.

Revision ID: 003
Revises: 002
Create Date: 2026-04-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE interviews SET candidate_email = lower(candidate_email)"))


def downgrade() -> None:
    pass  # cannot reverse — original casing is lost
