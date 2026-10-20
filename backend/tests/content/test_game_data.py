"""Task 15: 升级数据表与导入 CLI 的失败测试。

重点是三条容易算错的约定：

1. **``upgrade.cost[i]`` 对应 ``level = i + 1``**，即"从 level 升到 level+1"。
   差一格会让用户算出完全错误的升级成本，而这种错误没有任何报错。
2. **导入必须幂等**。重复执行不能翻倍，且返回的行数恒等于输入行数（R5）。
3. **超级兵种与未知类别不产生行** —— 但也不能让整个导入崩掉。
"""

import json

import pytest
from sqlalchemy import func, select

from app.coc.devfixtures import FIXTURES_DIR
from app.content.game_data import (
    fetch_units_data,
    import_upgrade_items,
    units_to_rows,
)
from app.db.models import UpgradeItem

#: 迷你数据集住在夹具目录（包内），不再用 cwd 相对路径 —— cwd 相对路径换个目录就断。
MINI = json.loads(
    (FIXTURES_DIR / "coc_units_mini.json").read_text(encoding="utf-8")
)


def _rows_for(rows, name):
    return [r for r in rows if r["name"] == name]


# --------------------------------------------------------------------------- #
# 索引映射：差一格就是灾难
# --------------------------------------------------------------------------- #


def test_units_to_rows_generates_one_row_per_level():
    rows = units_to_rows(MINI)
    barbarian = _rows_for(rows, "Barbarian")
    assert len(barbarian) == 12, "upgrade.cost 有 12 项就该产生 12 行"
    # 索引 0 表示 1 → 2 级
    assert barbarian[0]["level"] == 1
    assert barbarian[0]["elixir"] == 10000
    assert barbarian[11]["level"] == 12
    assert barbarian[11]["elixir"] == 120000


def test_levels_are_contiguous_and_ascending():
    """等级必须连续递增。漏一格会让"升到 N 级总共花多少"算错。"""
    levels = [r["level"] for r in _rows_for(units_to_rows(MINI), "Barbarian")]
    assert levels == list(range(1, len(levels) + 1))


# --------------------------------------------------------------------------- #
# 资源分列
# --------------------------------------------------------------------------- #


def test_units_to_rows_maps_resources_to_columns():
    rows = units_to_rows(MINI)

    elixir = _rows_for(rows, "Barbarian")[0]
    assert elixir["elixir"] == 10000
    assert elixir["gold"] is None
    assert elixir["dark_elixir"] is None

    dark = _rows_for(rows, "Barbarian King")[0]
    assert dark["dark_elixir"] == 20000
    assert dark["gold"] is None
    assert dark["elixir"] is None


def test_units_to_rows_writes_nothing_for_unknown_resource():
    """未列出的资源（Builder Elixir）不写任何成本列 —— 宁可留空不可记错。"""
    units = [
        {
            "name": "Something",
            "category": "hero",
            "village": "builderBase",
            "upgrade": {"cost": [5000], "time": [10], "resource": "Builder Elixir"},
        }
    ]
    row = units_to_rows(units)[0]
    assert row["gold"] is None
    assert row["elixir"] is None
    assert row["dark_elixir"] is None
    # 成本本身仍然是已知的，只是没有对应的货币列
    assert row["build_time_seconds"] == 10


def test_units_to_rows_handles_gold_resources():
    units = [
        {
            "name": "Wall",
            "category": "equipment",
            "village": "home",
            "upgrade": {"cost": [1000], "time": [5], "resource": "Gold"},
        }
    ]
    row = units_to_rows(units)[0]
    assert row["gold"] == 1000


# --------------------------------------------------------------------------- #
# 解锁条件
# --------------------------------------------------------------------------- #


def test_units_to_rows_maps_unlock_hall_to_required_townhall_level():
    row = _rows_for(units_to_rows(MINI), "Barbarian")[0]
    assert row["required_townhall_level"] == 1

    king = _rows_for(units_to_rows(MINI), "Barbarian King")[0]
    assert king["required_townhall_level"] == 5


def test_builder_base_level_only_for_builder_base_village():
    """主村单位不该被塞 required_builder_base_level。"""
    barbarian = _rows_for(units_to_rows(MINI), "Barbarian")[0]
    assert barbarian["required_builder_base_level"] is None

    king = _rows_for(units_to_rows(MINI), "Barbarian King")[0]
    assert king["required_builder_base_level"] == 2


# --------------------------------------------------------------------------- #
# 跳过：不是崩溃
# --------------------------------------------------------------------------- #


def test_units_to_rows_skips_super_troops():
    """超级兵种没有 upgrade.cost 数组，跳过而非报错。

    它们在 RAW_SUPER_UNITS 里，结构是 resourceCost + cooldown。
    """
    rows = units_to_rows(MINI)
    assert _rows_for(rows, "Super Barbarian") == []


def test_units_to_rows_skips_building_category():
    """building 类不在这条路径里 —— 其解锁条件结构不同，另走一条路。"""
    rows = units_to_rows(MINI)
    assert _rows_for(rows, "Wall") == []


def test_units_to_rows_skips_units_without_upgrade():
    """缺 upgrade 的条目（如只有解锁条件的建筑）跳过。"""
    rows = units_to_rows(MINI)
    assert _rows_for(rows, "Inferno Tower") == []


def test_units_to_rows_skips_unknown_category():
    units = [
        {"name": "Pet", "category": "pet", "village": "home",
         "upgrade": {"cost": [100], "time": [1], "resource": "Gold"}}
    ]
    assert units_to_rows(units) == []


def test_units_to_rows_skips_unknown_category_without_failing_the_batch():
    """一条脏数据不该让整批导入失败 —— 剩下 12 行仍要产出。"""
    units = MINI + [
        {"name": "Garbage", "category": "unknown", "village": "home",
         "upgrade": {"cost": [100]}},
        "not a dict",
        None,
    ]
    rows = units_to_rows(units)
    assert len(_rows_for(rows, "Barbarian")) == 12
    assert _rows_for(rows, "Garbage") == []


def test_units_to_rows_tolerates_missing_time_array():
    units = [
        {"name": "X", "category": "troop", "village": "home",
         "upgrade": {"cost": [100, 200], "resource": "Elixir"}}
    ]
    rows = units_to_rows(units)
    assert [r["level"] for r in rows] == [1, 2]
    assert all(r["build_time_seconds"] is None for r in rows)


def test_units_to_rows_handles_empty_input():
    assert units_to_rows([]) == []


# --------------------------------------------------------------------------- #
# 导入幂等（规格 §10.3 第 8 条）
# --------------------------------------------------------------------------- #


async def test_import_is_idempotent(session):
    rows = units_to_rows(MINI)
    first = await import_upgrade_items(session, rows)
    second = await import_upgrade_items(session, rows)

    # 返回值恒等于输入行数（R5），不是"实际变更行数"
    assert first == second == len(rows)

    total = (
        await session.execute(select(func.count()).select_from(UpgradeItem))
    ).scalar_one()
    assert total == first, "重复导入不能让行数翻倍"


async def test_import_updates_existing_rows_in_place(session):
    rows = units_to_rows(MINI)
    await import_upgrade_items(session, rows)
    before = (
        await session.execute(select(func.count()).select_from(UpgradeItem))
    ).scalar_one()

    # 模拟数据修正：同一单位同等级，成本变了
    modified = [dict(r) for r in rows]
    modified[0]["elixir"] = 99999
    await import_upgrade_items(session, modified)

    after = (
        await session.execute(select(func.count()).select_from(UpgradeItem))
    ).scalar_one()
    assert after == before, "upsert 应更新已有行而不是新增"

    stored = (
        await session.execute(
            select(UpgradeItem)
            .where(UpgradeItem.name == "Barbarian", UpgradeItem.level == 1)
        )
    ).scalar_one()
    assert stored.elixir == 99999


async def test_import_with_empty_rows_is_a_noop(session):
    assert await import_upgrade_items(session, []) == 0
    total = (
        await session.execute(select(func.count()).select_from(UpgradeItem))
    ).scalar_one()
    assert total == 0


async def test_imported_rows_roundtrip_correctly(session):
    await import_upgrade_items(session, units_to_rows(MINI))
    row = (
        await session.execute(
            select(UpgradeItem)
            .where(UpgradeItem.name == "Barbarian King", UpgradeItem.level == 1)
            .where(UpgradeItem.category == "hero")
        )
    ).scalar_one()
    assert row.village == "builderBase"
    assert row.dark_elixir == 20000
    assert row.build_time_seconds == 3600
    assert row.required_builder_base_level == 2


async def test_import_does_not_overwrite_manual_name_zh(session):
    """人工填的 ``name_zh`` 不该被重跑冲掉。

    导入阶段恒写 None，若把它放进 upsert 的更新列，任何一次重跑都会清空翻译。
    """
    rows = units_to_rows(MINI)
    await import_upgrade_items(session, rows)

    from sqlalchemy import update

    await session.execute(
        update(UpgradeItem)
        .where(UpgradeItem.name == "Barbarian")
        .values(name_zh="野蛮人")
    )
    await session.commit()

    await import_upgrade_items(session, rows)

    row = (
        await session.execute(
            select(UpgradeItem)
            .where(UpgradeItem.name == "Barbarian", UpgradeItem.level == 1)
        )
    ).scalar_one()
    assert row.name_zh == "野蛮人", (
        "重跑导入把人工填的 name_zh 冲掉了 —— upsert 的 set_ 里不该含 name_zh"
    )


def test_units_to_rows_leaves_name_zh_and_builder_count_null():
    """翻译不在导入阶段猜 —— 填来源不明的翻译比留空更糟。"""
    rows = units_to_rows(MINI)
    assert all(r["name_zh"] is None for r in rows)
    assert all(r["builder_count"] is None for r in rows)
    assert all(r["notes"] is None for r in rows)


# --------------------------------------------------------------------------- #
# 下载路径
# --------------------------------------------------------------------------- #


async def test_fetch_units_data_uses_the_cache(monkeypatch, tmp_path):
    """给了 cache_dir 且 tarball 已存在时**不得联网**。

    否则每次调数据都要重新下 2MB 的包，调试成本极高。
    """
    from app.content.game_data import NPM_PACKAGE, NPM_VERSION, _download_tarball

    tarball = tmp_path / f"{NPM_PACKAGE}-{NPM_VERSION}.tgz"
    tarball.write_bytes(b"not-a-real-tarball")

    def boom(*a, **kw):
        raise AssertionError("命中缓存时不应联网")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    assert await _download_tarball(tmp_path) == tarball


async def test_fetch_units_data_returns_both_unit_lists(monkeypatch, tmp_path):
    """返回值必须同时含 RAW_UNITS 与 RAW_SUPER_UNITS。

    上层据此决定丢弃超级兵种 —— 若这里就只返回一个键，"为什么少了几百行"
    会变成一个查不到答案的问题。
    """
    from app.content.game_data import (
        RAW_SUPER_UNITS_KEY,
        RAW_UNITS_KEY,
        fetch_units_data,
    )

    monkeypatch.setattr(
        "app.content.game_data._download_tarball",
        _async_return(tmp_path / "x.tgz"),
    )
    monkeypatch.setattr(
        "app.content.game_data._read_raw_json",
        _sync_return({RAW_UNITS_KEY: [{"name": "Barbarian"}], RAW_SUPER_UNITS_KEY: [{"name": "SB"}]}),
    )

    data = await fetch_units_data(cache_dir=tmp_path)
    assert data[RAW_UNITS_KEY][0]["name"] == "Barbarian"
    assert data[RAW_SUPER_UNITS_KEY][0]["name"] == "SB"


def test_read_raw_json_reports_a_changed_layout(tmp_path):
    """上游改了目录结构时必须响亮失败，而不是静默返回空。"""
    import io
    import tarfile

    from app.content.game_data import _read_raw_json

    path = tmp_path / "pkg.tgz"
    with tarfile.open(path, "w:gz") as tar:
        payload = json.dumps({"RAW_UNITS": []}).encode()
        info = tarfile.TarInfo("package/dist/somewhere-else.json")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))

    with pytest.raises(RuntimeError, match="raw.json"):
        _read_raw_json(path)


def test_read_raw_json_parses_a_normal_layout(tmp_path):
    import io
    import tarfile

    from app.content.game_data import _read_raw_json

    path = tmp_path / "pkg.tgz"
    payload = json.dumps({"RAW_UNITS": [{"name": "Barbarian"}]}).encode()
    with tarfile.open(path, "w:gz") as tar:
        info = tarfile.TarInfo("package/dist/util/raw.json")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))

    assert _read_raw_json(path)["RAW_UNITS"][0]["name"] == "Barbarian"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def test_cli_exposes_expected_commands():
    """命令集合恰为这三个：导入升级数据 + 开发期榜单种子 + 手动采集。

    原计划里还有 create-admin，但后台认证走环境变量且规格中不存在管理员表 ——
    保留它等于凭空引入一张表或第二条凭据来源（由下方
    test_cli_has_no_create_admin_command 继续把关）。

    seed-dev-rankings 是 COCPersonal 规格新增的**开发期**命令：没有真实 Token
    时把榜单夹具灌进库，排行榜页才有数据可看。

    collect 是**运维**命令：换好真实 Token 后不必干等 cron（rankings 每 6 小时）
    就能立刻采一次；它走的是调度器同一条路径（app.collector.service.run_job）。
    """
    from app.cli import build_parser

    parser = build_parser()
    actions = [a for a in parser._actions if a.dest == "command"]
    assert len(actions) == 1
    assert set(actions[0].choices) == {
        "import-game-data",
        "seed-dev-rankings",
        "collect",
    }


def test_cli_has_no_create_admin_command():
    import app.cli as cli

    assert not hasattr(cli, "cmd_create_admin")


@pytest.mark.asyncio
async def test_cmd_import_game_data_only_uses_raw_units(monkeypatch, session):
    """``RAW_SUPER_UNITS`` 必须被丢弃 —— 它们产生不了等级行。"""
    from app.cli import cmd_import_game_data

    monkeypatch.setattr(
        "app.cli.fetch_units_data",
        _async_return(
            {
                "RAW_UNITS": MINI,
                "RAW_SUPER_UNITS": [{"name": "Super Barbarian"}],
            }
        ),
    )

    count = await cmd_import_game_data(session=session)

    assert count == 18, "12（野蛮人）+ 6（野蛮人王）"
    stored = (
        await session.execute(select(UpgradeItem.name).distinct())
    ).scalars().all()
    assert "Super Barbarian" not in stored
    assert set(stored) == {"Barbarian", "Barbarian King"}


def _async_return(value):
    async def _call(*a, **kw):
        return value

    return _call


def _sync_return(value):
    def _call(*a, **kw):
        return value

    return _call