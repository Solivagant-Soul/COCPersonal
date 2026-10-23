"""War Report 阵容表 ``warreport_armies`` 与两类赛季榜（迁移 0012）。

表结构的两个消费方决定了这里要盯的东西：

* Task 5 的整表替换把 ``army_row(...)`` 的输出直接 ``WarReportArmy(**row)`` ——
  列名/可空性差一格就是 INSERT 期整批炸掉（那时 ``DELETE`` 已执行）；
* Task 6 从 ``rankings`` 读 ``wr_season_*``，类型没加进去就查不到数据。

因此第一条测试用 ``to_regclass`` 验「表真的建出来了」：空迁移是本项目踩过的坑，
它在 ``alembic upgrade head`` 下**不会报错**，只会让后面每条查询都 500。
"""

import datetime as dt
from datetime import UTC

import pytest
from sqlalchemy import UniqueConstraint, insert, select, text
from sqlalchemy.exc import IntegrityError

from app.collector.rankings_service import RankingKind
from app.db.models import WarReportArmy


def _row(**over):
    base = {
        "position": 1, "name": "Thrower", "canonical_key": "k1",
        "army_share_code": "sc", "army_link": "https://link",
        "player_count": 1, "use_count": 2, "percentage": 50.0,
        "average_stars": 2.5, "average_destruction": 90.0,
        "fetched_at": dt.datetime.now(UTC),
    }
    base.update(over)
    return base


async def test_warreport_armies_table_exists(session):
    exists = (
        await session.execute(text("SELECT to_regclass('warreport_armies')"))
    ).scalar_one()
    assert exists is not None


async def test_army_round_trip(session):
    session.add(WarReportArmy(**_row()))
    await session.commit()
    row = (await session.execute(select(WarReportArmy))).scalar_one()
    assert row.name == "Thrower"
    assert row.canonical_key == "k1"
    # 浮点列存的是 float，不是被截成 int
    assert row.average_stars == 2.5
    assert row.average_destruction == 90.0


async def test_canonical_key_is_unique(session):
    """用 ``insert()`` 而非 ``session.add``：后者会被 identity map 提前拦下，
    约束根本到不了数据库，成了假测试。
    """
    await session.execute(insert(WarReportArmy).values(_row()))
    with pytest.raises(IntegrityError):
        await session.execute(
            insert(WarReportArmy).values(_row(position=2))
        )
    await session.rollback()


async def test_constraint_and_index_names_match_migration(session):
    """唯一约束名必须与迁移里的手写名逐字一致。

    ``Base`` 没有配 ``naming_convention``，若模型侧写成 ``unique=True``，落库名会是
    Postgres 自动生成的 ``warreport_armies_canonical_key_key``；模型与迁移对不上时
    每次 ``--autogenerate`` 都会反复生成「删约束/建约束」。这条测试拿数据库里的
    真实对象名与模型声明比对，专门盯这种漂移。
    """
    db_constraints = set(
        (
            await session.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid = 'warreport_armies'::regclass AND contype = 'u'"
                )
            )
        ).scalars()
    )
    db_indexes = set(
        (
            await session.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'warreport_armies'")
            )
        ).scalars()
    )

    model_constraints = {
        c.name
        for c in WarReportArmy.__table__.constraints
        if isinstance(c, UniqueConstraint)
    }
    assert db_constraints == model_constraints == {"uq_warreport_armies_canonical_key"}
    assert "ix_warreport_armies_position" in db_indexes


def test_new_ranking_kinds_exist():
    assert str(RankingKind.wr_season_players) == "wr_season_players"
    assert str(RankingKind.wr_season_clans) == "wr_season_clans"
