"""dev 夹具上游：没有真实 Supercell Token 时，用 ``app/coc/fixtures/`` 里的
placeholder 响应顶替官方 API。

**只在开发期启用**：``COC_API_TOKEN`` 为空或等于占位值（``PLACEHOLDER``）时，
``app.main.create_app()`` 给 ``CocClient`` 注入一个 :class:`FixtureTransport`。
生产（真实 token）永远走 httpx 默认传输，本模块不参与。

为什么用 transport 而不是替身 client：``CocClient`` 本来就有一个
``transport`` 注入点（测试用 ``httpx.MockTransport``）。复用它意味着夹具
上游与真实上游走**完全相同的** client 代码路径——限速、错误映射、JSON 解析
全部照旧，夹具只替换最底层的字节来源。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

#: 夹具目录。**必须放在包内**（``app/coc/fixtures/``）：生产镜像里应用是
#: ``pip install .`` 装进 site-packages 的，仓库相对路径（``../tests/fixtures``）
#: 在镜像里根本不存在 —— 这条已经咬过两次（``seed-dev-rankings`` 与夹具上游
#: 在镜像里双双 ``FileNotFoundError``，后者等于**无 Token 部署的所有上游读取全 500**）。
#: 包内定位 + ``pyproject.toml`` 的 package-data 声明，夹具才会随 wheel 一起进镜像。
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

#: 视为"没有真实 token"的取值。大小写不敏感，前后空白忽略。
_PLACEHOLDER_TOKENS = frozenset({"", "PLACEHOLDER"})


def is_placeholder_token(token: str) -> bool:
    """token 为空或占位值时返回 True（此时应启用夹具上游）。"""
    return (token or "").strip().upper() in _PLACEHOLDER_TOKENS


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _search_payload() -> dict[str, Any]:
    """``/clans/search`` 的响应。官方是 ``{"items": [...]}``，这里用部落详情
    造一条——搜索用的字段（tag/name/clanLevel/members）它都有。"""
    clan = _load("clan_detail.json")
    item = {
        "tag": clan.get("tag"),
        "name": clan.get("name"),
        "clanLevel": clan.get("clanLevel"),
        "members": clan.get("members"),
        "clanPoints": clan.get("clanPoints"),
        "location": clan.get("location"),
        "badgeUrls": clan.get("badgeUrls"),
    }
    return {"items": [item]}


class FixtureTransport(httpx.AsyncBaseTransport):
    """按 URL 路径把请求路由到对应夹具文件。未收录的路径返回 404 notFound，
    形状与官方一致，好让 client 的错误映射照常走一遍。"""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        payload, status = self._route(request.url.path)
        return httpx.Response(status, json=payload, request=request)

    def _route(self, path: str) -> tuple[dict[str, Any], int]:
        # 顺序要紧：/clans/search 也含 "/clans/"，必须先判它；
        # /rankings/players 也含 "/players/"，必须在玩家详情之前判。
        if "/clans/search" in path:
            return _search_payload(), 200
        if "/rankings/clans" in path:
            return _load("ranking_clans.json"), 200
        if "/rankings/players" in path:
            return _load("ranking_players.json"), 200
        if "/players/" in path and path.endswith("/battlelog"):
            return _load("player_battlelog.json"), 200
        if "/players/" in path:
            return _load("player_profile.json"), 200
        if "/clans/" in path:
            return _load("clan_detail.json"), 200
        if path.endswith("/locations"):
            return _load("locations.json"), 200
        return {"reason": "notFound"}, 404
