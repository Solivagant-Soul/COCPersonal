"""TTL 表。

数值全部来自规格 §4.3，不是拍脑袋。每条 TTL 的存在意义：官方建议不同、
数据变动频率不同。改这里 = 改对官方的请求频率，直接影响令牌桶压力和限流风险。
"""

import pytest

from app.cache.ttl import TTL, get_ttl


def test_clan_and_members_share_300s():
    """官方文档建议 1–5 min。"""
    assert get_ttl("clan") == 300
    assert get_ttl("clan_members") == 300


def test_currentwar_is_120s():
    """战斗中实时变化，官方建议 1–2 min。"""
    assert get_ttl("currentwar") == 120


def test_warlog_is_600s():
    """追加型，平时不变。"""
    assert get_ttl("warlog") == 600


def test_cwl_leaguegroup_is_600s():
    assert get_ttl("cwl") == 600


def test_player_is_300s():
    assert get_ttl("player") == 300


def test_static_dictionaries_are_one_day():
    """维表静态字典：locations / leaguetiers / labels。"""
    for resource in ("locations", "leaguetiers", "labels"):
        assert get_ttl(resource) == 86400


def test_leagues_are_one_hour():
    """war / capital / builderbase 三种联赛合一。"""
    assert get_ttl("leagues") == 3600


def test_rankings_and_seasons_are_six_hours():
    """名次变动不频繁。"""
    assert get_ttl("rankings") == 21600
    assert get_ttl("seasons") == 21600


def test_goldpass_is_one_hour():
    assert get_ttl("goldpass") == 3600


def test_unknown_resource_raises_key_error():
    """静默落默认值会掩盖拼写错误——宁可炸。"""
    with pytest.raises(KeyError):
        get_ttl("clan_warlog")  # 常见笔误：正确的键是 "warlog"


def test_ttl_table_covers_every_documented_resource():
    """规格 §4.3 的每一类资源都要有键。"""
    expected = {
        "clan", "clan_members", "currentwar", "warlog", "cwl", "player",
        "leaguetiers", "locations", "labels", "leagues", "rankings",
        "seasons", "goldpass",
    }
    assert expected <= set(TTL), f"缺少: {expected - set(TTL)}"


def test_all_ttls_are_positive_seconds():
    for resource, seconds in TTL.items():
        assert isinstance(seconds, int), f"{resource} 的 TTL 不是 int"
        assert seconds > 0, f"{resource} 的 TTL 非正数"
