"""widen season id columns

Revision ID: a7f3c1d90e42
Revises: d4c8a36b19e6
Create Date: 2026-10-21

赛季 id 从 2026-09 起换成了新格式 ``v2-2026-09-28T05:00:00Z``（23 字符），
旧的 ``seasons.id VARCHAR(10)`` / ``rankings.season_id VARCHAR(16)`` 装不下，
插入会报 ``StringDataRightTruncation`` —— 采集整轮 failed，而且原因埋在
asyncpg 的报错里。两列都放宽到 64。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a7f3c1d90e42"
down_revision: Union[str, Sequence[str], None] = "d4c8a36b19e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "seasons",
        "id",
        existing_type=sa.String(10),
        type_=sa.String(64),
        existing_nullable=False,
    )
    op.alter_column(
        "rankings",
        "season_id",
        existing_type=sa.String(16),
        type_=sa.String(64),
        existing_nullable=True,
    )


def downgrade() -> None:
    # 先删掉装不进旧列宽的 v2 赛季行，否则 ALTER 会直接失败。
    # 这是真实的数据丢弃，降级前请想清楚。
    op.execute("DELETE FROM rankings WHERE length(season_id) > 16")
    op.execute("DELETE FROM seasons WHERE length(id) > 10")
    op.alter_column(
        "rankings",
        "season_id",
        existing_type=sa.String(64),
        type_=sa.String(16),
        existing_nullable=True,
    )
    op.alter_column(
        "seasons",
        "id",
        existing_type=sa.String(64),
        type_=sa.String(10),
        existing_nullable=False,
    )
