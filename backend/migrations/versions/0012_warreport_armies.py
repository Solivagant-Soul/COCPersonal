"""warreport armies table

Revision ID: c3f9a1b7d204
Revises: b2e8f4c17a93
Create Date: 2026-10-23

Army usage statistics from the third-party War Report API
(https://api.warreport.app). The table is replaced wholesale on every
collection run (DELETE + INSERT in one transaction), so it keeps no history and
has no foreign keys.

The unique constraint on ``canonical_key`` and the index on ``position`` are
named explicitly to match ``WarReportArmy.__table_args__``. ``Base`` has no
``naming_convention``; relying on implicit names would make the model and the
database disagree and every future ``--autogenerate`` would emit a
drop/create-constraint pair.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3f9a1b7d204"
down_revision: Union[str, Sequence[str], None] = "b2e8f4c17a93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "warreport_armies",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("canonical_key", sa.Text(), nullable=False),
        sa.Column("army_share_code", sa.Text(), nullable=False),
        sa.Column("army_link", sa.Text(), nullable=False),
        sa.Column("player_count", sa.Integer(), nullable=False),
        sa.Column("use_count", sa.Integer(), nullable=False),
        sa.Column("percentage", sa.Float(), nullable=False),
        sa.Column("average_stars", sa.Float(), nullable=False),
        sa.Column("average_destruction", sa.Float(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "canonical_key", name="uq_warreport_armies_canonical_key"
        ),
    )
    op.create_index(
        "ix_warreport_armies_position",
        "warreport_armies",
        ["position"],
        unique=False,
    )


def downgrade() -> None:
    # The unique constraint is dropped together with the table.
    op.drop_index("ix_warreport_armies_position", table_name="warreport_armies")
    op.drop_table("warreport_armies")
