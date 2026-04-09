"""Normalize user emails to lowercase and enforce case-insensitive uniqueness.

Revision ID: 002
Revises: 001
Create Date: 2026-04-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Find duplicate users where the only difference is email case.
    #    For each group, keep the row with the earliest created_at and
    #    re-point all interviews belonging to the duplicates to the survivor.
    duplicates = conn.execute(
        sa.text(
            """
            SELECT lower(email) AS lower_email, array_agg(id::text ORDER BY created_at ASC) AS ids
            FROM users
            GROUP BY lower(email)
            HAVING count(*) > 1
            """
        )
    ).fetchall()

    for row in duplicates:
        ids = row[1]          # sorted oldest-first
        canonical_id = ids[0]
        duplicate_ids = ids[1:]

        # Re-assign interviews and delete each duplicate one at a time
        # (avoids asyncpg's inability to bind uuid[] arrays in prepared statements)
        for dup_id in duplicate_ids:
            conn.execute(
                sa.text(
                    "UPDATE interviews SET user_id = CAST(:canonical AS UUID)"
                    " WHERE user_id = CAST(:dup AS UUID)"
                ),
                {"canonical": canonical_id, "dup": dup_id},
            )
            conn.execute(
                sa.text("DELETE FROM users WHERE id = CAST(:dup AS UUID)"),
                {"dup": dup_id},
            )

    # 2. Lowercase all remaining email values
    conn.execute(sa.text("UPDATE users SET email = lower(email)"))

    # 3. Drop the old case-sensitive unique index and create a new functional
    #    unique index on lower(email) so future inserts are also protected.
    op.drop_index("ix_users_email", table_name="users")
    op.create_index(
        "ix_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_users_email_lower", table_name="users")
    op.create_index("ix_users_email", "users", ["email"], unique=True)
