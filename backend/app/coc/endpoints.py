"""Supercell 官方 30 个接口的薄封装。

职责边界：**只**负责把参数拼成正确的 URL 与 query，返回官方原始 dict。
任何"整理数据"的想法都属于 ``mappers.py``。这里越薄越好 —— 每次官方加字段，
需要改的是 mapper，而不是这里。

约定：
- 凡涉及 tag 的路径一律调 ``quote_tag``，不得自行拼接（见 ``tags.py`` 的说明）。
- 排名类接口的 ``locationId`` 走**路径**，不走 query。
- 分页上限见 ``clamp_page_size``（Task 9 提供），这里只管透传调用方给的值。
"""

from __future__ import annotations

from typing import Any

from app.coc.client import CocClient
from app.coc.tags import quote_tag

# 官方接口的基址由 CocClient 统一持有，这里只写相对路径。

# --------------------------------------------------------------------------- #
# 部落
# --------------------------------------------------------------------------- #


async def search_clans(
    client: CocClient,
    *,
    name: str | None = None,
    war_frequency: str | None = None,
    location_id: int | None = None,
    min_members: int | None = None,
    max_members: int | None = None,
    min_clan_points: int | None = None,
    min_clan_level: int | None = None,
    limit: int | None = None,
    after: str | None = None,
    before: str | None = None,
    label_id: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for key, value in (
        ("name", name),
        ("warFrequency", war_frequency),
        ("locationId", location_id),
        ("minMembers", min_members),
        ("maxMembers", max_members),
        ("minClanPoints", min_clan_points),
        ("minClanLevel", min_clan_level),
        ("limit", limit),
        ("after", after),
        ("before", before),
        ("labelId", label_id),
    ):
        if value is not None:
            params[key] = value
    return await client.get("/clans", params=params)


async def get_clan(client: CocClient, tag: str) -> dict[str, Any]:
    return await client.get(f"/clans/{quote_tag(tag)}")


async def get_clan_members(
    client: CocClient, tag: str, *, limit: int | None = None
) -> dict[str, Any]:
    params = {"limit": limit} if limit is not None else None
    return await client.get(f"/clans/{quote_tag(tag)}/members", params=params)


async def get_clan_warlog(client: CocClient, tag: str) -> dict[str, Any]:
    return await client.get(f"/clans/{quote_tag(tag)}/warlog")


async def get_clan_currentwar(client: CocClient, tag: str) -> dict[str, Any]:
    return await client.get(f"/clans/{quote_tag(tag)}/currentwar")


async def get_clan_currentwar_leaguegroup(
    client: CocClient, tag: str
) -> dict[str, Any]:
    return await client.get(f"/clans/{quote_tag(tag)}/currentwar/leaguegroup")


async def get_clanwarleague_war(client: CocClient, war_tag: str) -> dict[str, Any]:
    return await client.get(f"/clanwarleagues/wars/{quote_tag(war_tag)}")


async def get_clan_capitalraidseasons(
    client: CocClient, tag: str
) -> dict[str, Any]:
    return await client.get(f"/clans/{quote_tag(tag)}/capitalraidseasons")


# --------------------------------------------------------------------------- #
# 玩家
# --------------------------------------------------------------------------- #


async def get_player(client: CocClient, tag: str) -> dict[str, Any]:
    return await client.get(f"/players/{quote_tag(tag)}")


async def verify_player_token(
    client: CocClient, tag: str, token: str
) -> dict[str, Any]:
    """校验 API token。这是官方唯一的写操作语义接口，但本身是 POST + 只读校验。"""
    return await client.post(
        f"/players/{quote_tag(tag)}/verifytoken", {"token": token}
    )


# --------------------------------------------------------------------------- #
# 联赛 / 层级 / 标签 / 赛季
# --------------------------------------------------------------------------- #


async def get_leaguetiers(client: CocClient) -> dict[str, Any]:
    return await client.get("/leaguetiers")


async def get_leaguetier(client: CocClient, league_id: int) -> dict[str, Any]:
    return await client.get(f"/leaguetiers/{league_id}")


async def get_warleagues(client: CocClient) -> dict[str, Any]:
    return await client.get("/warleagues")


async def get_warleague(client: CocClient, league_id: int) -> dict[str, Any]:
    return await client.get(f"/warleagues/{league_id}")


async def get_capitalleagues(client: CocClient) -> dict[str, Any]:
    return await client.get("/capitalleagues")


async def get_capitalleague(client: CocClient, league_id: int) -> dict[str, Any]:
    return await client.get(f"/capitalleagues/{league_id}")


async def get_builderbaseleagues(client: CocClient) -> dict[str, Any]:
    return await client.get("/builderbaseleagues")


async def get_builderbaseleague(client: CocClient, league_id: int) -> dict[str, Any]:
    return await client.get(f"/builderbaseleagues/{league_id}")


async def get_leagues(client: CocClient, limit: int | None = None) -> dict[str, Any]:
    """联赛列表（``/leagues``，id 为 ``290000xx``）。

    **不要和 ``/leaguetiers`` 混用**：tier 的 id 是 ``105000xxx``（Legend I/II/III），
    而 ``/leagues/{id}/seasons`` 只认这里的 id。
    """
    params = {"limit": limit} if limit is not None else None
    return await client.get("/leagues", params)


async def get_league_seasons(
    client: CocClient,
    league_id: int,
    limit: int | None = None,
    after: str | None = None,
) -> dict[str, Any]:
    """联赛赛季清单。

    官方**由旧到新**分页返回（2015-07 起），``limit`` 上限 50；要当前赛季
    必须顺着 ``paging.cursors.after`` 翻到最后一页。
    """
    params: dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    if after is not None:
        params["after"] = after
    return await client.get(f"/leagues/{league_id}/seasons", params or None)


async def get_capitalleague_seasons(
    client: CocClient, league_id: int
) -> dict[str, Any]:
    return await client.get(f"/capitalleagues/{league_id}/seasons")


async def get_league_season_players(
    client: CocClient, league_id: int, season_id: str, limit: int | None = None
) -> dict[str, Any]:
    """赛季玩家排名。

    **官方默认只返回 10 条**（``limit`` 上限 50），不显式传的话赛季榜会静默
    变成"只有前 10 名"。
    """
    params = {"limit": limit} if limit is not None else None
    return await client.get(f"/leagues/{league_id}/seasons/{season_id}", params)


async def get_clan_labels(client: CocClient) -> dict[str, Any]:
    return await client.get("/labels/clans")


async def get_player_labels(client: CocClient) -> dict[str, Any]:
    return await client.get("/labels/players")


# --------------------------------------------------------------------------- #
# 地区与榜单
# --------------------------------------------------------------------------- #


async def get_locations(client: CocClient) -> dict[str, Any]:
    return await client.get("/locations")


async def get_location(client: CocClient, location_id: int) -> dict[str, Any]:
    return await client.get(f"/locations/{location_id}")


async def get_clan_rankings(
    client: CocClient, location_id: int, *, limit: int | None = None
) -> dict[str, Any]:
    """locationId 走路径；limit 走 query。"""
    params = {"limit": limit} if limit is not None else None
    return await client.get(
        f"/locations/{location_id}/rankings/clans", params=params
    )


async def get_player_rankings(
    client: CocClient, location_id: int, *, limit: int | None = None
) -> dict[str, Any]:
    params = {"limit": limit} if limit is not None else None
    return await client.get(
        f"/locations/{location_id}/rankings/players", params=params
    )


async def get_clan_rankings_builder_base(
    client: CocClient, location_id: int, *, limit: int | None = None
) -> dict[str, Any]:
    params = {"limit": limit} if limit is not None else None
    return await client.get(
        f"/locations/{location_id}/rankings/clans-builder-base",
        params=params,
    )


async def get_player_rankings_builder_base(
    client: CocClient, location_id: int, *, limit: int | None = None
) -> dict[str, Any]:
    params = {"limit": limit} if limit is not None else None
    return await client.get(
        f"/locations/{location_id}/rankings/players-builder-base",
        params=params,
    )


async def get_capital_rankings(
    client: CocClient, location_id: int, *, limit: int | None = None
) -> dict[str, Any]:
    params = {"limit": limit} if limit is not None else None
    return await client.get(
        f"/locations/{location_id}/rankings/capitals", params=params
    )


# --------------------------------------------------------------------------- #
# 活动
# --------------------------------------------------------------------------- #


async def get_current_goldpass_season(client: CocClient) -> dict[str, Any]:
    return await client.get("/goldpass/seasons/current")
