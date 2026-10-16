"""composite pks for leagues and labels

Revision ID: e83ccfbb75ec
Revises: d6214f2b5dbe
Create Date: 2026-10-10

手写而非 autogenerate：**alembic 的 autogenerate 不检测主键变更**，跑出来是一份
只有 ``pass`` 的空迁移 —— 不报错、不失败、什么都没建。改主键必须自己写。
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e83ccfbb75ec'
down_revision: Union[str, Sequence[str], None] = 'd6214f2b5dbe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # leagues / labels 的模型注释都写着"id 在不同 kind 间可能重复"，但主键只有
    # id 单列，自相矛盾。后果：采集时 ON CONFLICT (id, kind) 找不到匹配的唯一索引
    # 直接报错；退而用 ON CONFLICT (id) 则会让一类联赛静默覆盖另一类。
    op.drop_constraint('leagues_pkey', 'leagues', type_='primary')
    op.create_primary_key('pk_leagues_id_kind', 'leagues', ['id', 'kind'])

    op.drop_constraint('labels_pkey', 'labels', type_='primary')
    op.create_primary_key('pk_labels_id_kind', 'labels', ['id', 'kind'])


def downgrade() -> None:
    # 降级前必须先处理跨 kind 的重复行，否则建单列主键时会因冲突失败。
    # 保留每组里 id 最小的那条，其余丢弃 —— 这些行本就是"被覆盖"的产物。
    op.execute(
        "DELETE FROM leagues WHERE ctid NOT IN ("
        "  SELECT min(ctid) FROM leagues GROUP BY id"
        ")"
    )
    op.execute(
        "DELETE FROM labels WHERE ctid NOT IN ("
        "  SELECT min(ctid) FROM labels GROUP BY id"
        ")"
    )
    op.drop_constraint('pk_leagues_id_kind', 'leagues', type_='primary')
    op.create_primary_key('leagues_pkey', 'leagues', ['id'])

    op.drop_constraint('pk_labels_id_kind', 'labels', type_='primary')
    op.create_primary_key('labels_pkey', 'labels', ['id'])