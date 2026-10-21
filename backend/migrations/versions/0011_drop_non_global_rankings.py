"""drop non-global rankings

Revision ID: b2e8f4c17a93
Revises: a7f3c1d90e42
Create Date: 2026-10-22

榜单收窄成「只保留全服（Global, 32000000）的部落榜与玩家榜」后，
``rankings`` 表里剩下的三类历史行成了纯垃圾：

- 都城榜 / 部落基地榜 / 玩家基地榜（``kind`` 不再被采集也不再被展示）
- 非全服地区的部落榜 / 玩家榜（``location_id != 32000000``）

它们不会自己消失 —— ``replace_rankings`` 只清自己那个 scope，别的 scope 的
旧行会一直躺在表里。几十个地区 × 5 类榜 × 200 行就是几十万行没人读的数据，
还会拖慢 ``/meta/freshness`` 的分组查询。

**赛季榜不动**：``kind = 'season_players'`` 的行走的是另一条 scope
（``league_id`` + ``season_id``，没有 ``location_id``），它还在用。
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2e8f4c17a93"
down_revision: Union[str, Sequence[str], None] = "a7f3c1d90e42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: 全服。官方地区 ID 的高位段是 32000000。
GLOBAL_LOCATION_ID = 32000000

#: 不再采集也不再展示的三类地区榜。
_DROPPED_KINDS = ("capitals", "clans_builder_base", "players_builder_base")


def upgrade() -> None:
    # 先删三类废榜（它们只可能是地区榜，location_id 非空）
    op.execute(
        "DELETE FROM rankings WHERE kind IN (%s)"
        % ", ".join("'%s'" % k for k in _DROPPED_KINDS)
    )
    # 再删非全服的地区榜。**不碰赛季榜**：赛季榜的 location_id 是 NULL，
    # 用「location_id IS NOT NULL AND location_id != 全服」这个条件正好排除它。
    op.execute(
        "DELETE FROM rankings "
        "WHERE location_id IS NOT NULL AND location_id != %d"
        % GLOBAL_LOCATION_ID
    )


def downgrade() -> None:
    # **数据删了就回不来** —— 降级只是把结构退回去，历史行需要重新采集。
    # 这里刻意不做任何恢复动作：凭空的行比没有行更糟（看起来有数据，其实过期）。
    pass
