"""app/coc/fixtures 下的真实响应样本。

这些文件是 Task 5 的手搓占位（无真实 Token），契约是：

1. 必须是合法 JSON；
2. 必须带 ``_source`` 标注，这样将来拿到 Token 的人一眼看出哪些是placeholder；
3. 字段名与官方 API 文档一致，供 Task 7 的 mapper 容错测试直接使用。

真实 Token 到位后，把四个文件整体替换为真实响应，然后删掉本文件里的
``test_*_are_marked_placeholders``（那时它们不再是占位）。

**夹具住在包内**（``app/coc/fixtures/``）不是 ``tests/`` 下：无 Token 时夹具上游
（``app/coc/devfixtures.py``）在**运行时**要读它们，而生产镜像只装 ``app/`` 包。
"""

import json

import pytest

from app.coc.devfixtures import FIXTURES_DIR

SAMPLE_FILES = [
    "clan_detail.json",
    "player_profile.json",
    "locations.json",
    "ranking_clans.json",
]


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_samples_are_valid_json(name):
    data = json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))
    assert data, f"{name} 内容为空"


@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_samples_are_marked_placeholders(name):
    """placeholder 必须自报身份，否则将来没人敢动它们。"""
    data = json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))
    assert "_source" in data, f"{name} 缺少 _source 标注"
    assert "_todo" in data, f"{name} 缺少 _todo 标注"


def test_clan_detail_has_expected_shape():
    data = json.loads((FIXTURES_DIR / "clan_detail.json").read_text(encoding="utf-8"))
    assert data["tag"].startswith("#")
    assert isinstance(data["memberList"], list)
    assert isinstance(data["clanCapital"]["districts"], list)


def test_player_profile_has_legend_and_optional_fields():
    data = json.loads((FIXTURES_DIR / "player_profile.json").read_text(encoding="utf-8"))
    assert data["townHallLevel"] >= 1
    assert "legendStatistics" in data
    # 有了部落的玩家才有 role
    assert data["role"] == "leader"


def test_locations_covers_both_country_and_non_country():
    data = json.loads((FIXTURES_DIR / "locations.json").read_text(encoding="utf-8"))
    items = data["items"]
    assert any(not i.get("isCountry") for i in items), "缺非国家地区样本"
    assert any(i.get("isCountry") and "countryCode" in i for i in items), "缺国家样本"


def test_ranking_clans_covers_zero_previous_rank():
    """previousRank == 0 表示新上榜，不能被当成「掉名次」处理。"""
    data = json.loads((FIXTURES_DIR / "ranking_clans.json").read_text(encoding="utf-8"))
    items = data["items"]
    assert items, "榜单为空"
    assert {i["previousRank"] for i in items} >= {0}, "缺 previousRank=0 的新上榜样本"
