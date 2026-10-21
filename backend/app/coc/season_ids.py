"""赛季 id 的格式与排序。

官方赛季 id 有两种形态（2026-10-21 线上实测）：

- 旧的 ``2015-07``（``YYYY-MM``）；
- 2026-05 起的 ``v2-2026-09-28T05:00:00Z``（``v2-`` + ISO 时刻，23 字符）。

**不能直接按字符串比先后**：``v2-`` 以字母开头，字典序永远大于任何 ``2026-xx``，
于是「下一个换回旧格式的赛季」会被判成比 v2 那个更旧。采集端（选当前赛季）和
API 端（赛季列表倒序）都必须先归一成日期再比，所以放在这里的共用函数里，
而不是各自实现一遍。

DB 列宽因此是 ``VARCHAR(64)``（迁移 0010），别再压回 10 / 16。
"""

from __future__ import annotations

import re

#: 抠 ``YYYY-MM`` 或 ``YYYY-MM-DDTHH:MM:SS``（可选结尾 ``Z``）。
_DATE_PREFIX = re.compile(r"\d{4}-\d{2}(?:-\d{2}T[\d:]+)?Z?")


def season_sort_key(season_id: str) -> str:
    """把赛季 id 归一成可比较的 ISO 日期前缀。

    ``2015-07`` → ``2015-07``；``v2-2026-09-28T05:00:00Z`` →
    ``2026-09-28T05:00:00Z``。认不出格式时原样返回（至少不会抛异常）。
    """
    match = _DATE_PREFIX.search(season_id)
    return match.group(0) if match else season_id
