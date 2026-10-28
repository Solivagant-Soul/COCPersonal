"""TTL 表（规格 §4.3）。

集中管理的理由：改一个 TTL 就等于改对 Supercell 的请求频率，
直接影响令牌桶压力与被限流的风险。散落在各路由里迟早有人改错。

数值的依据写在本文件每一行旁边——它们不是拍脑袋：

- clan / members / player：300s，官方文档建议 1–5 min
- currentwar：120s，战斗中实时变化，官方建议 1–2 min
- warlog / CWL leaguegroup：600s，追加型，平时不变
- leaguetiers / locations / labels：86400s，静态字典
- leagues：3600s，赛季更替才变
- rankings / seasons：21600s，名次变动不频繁
- goldpass：3600s，月卡更替
"""

from __future__ import annotations

TTL: dict[str, int] = {
    # 部落
    "clan": 300,
    "clan_members": 300,
    "currentwar": 120,
    "warlog": 600,
    "cwl": 600,
    # 玩家
    "player": 300,
    # 战斗日志：一轮传奇约 10 分钟，60s 只用来挡连点刷新，不做长期缓存
    "battlelog": 60,
    # 静态字典
    "leaguetiers": 86_400,
    "locations": 86_400,
    "labels": 86_400,
    "leagues": 3_600,
    # 榜单
    "rankings": 21_600,
    "seasons": 21_600,
    "goldpass": 3_600,
}


def get_ttl(resource: str) -> int:
    """取某资源的 TTL 秒数。

    未知资源**抛 KeyError** 而不是落默认值：静默落默认会掩盖拼写错误，
    让某类数据以错误的新鲜度提供服务，而这种错误在测试里看不出来。
    """
    return TTL[resource]
