"""五张维表（规格 §5.1）。

采集顺序自由：这些表的字段构造不依赖任何业务表，而业务表又**不**建外键到它们
（§5.6），所以任一表先落库都不会触发外键错误。
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

from sqlalchemy import (
    DateTime,
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# 联赛 / 标签的取值集合。用 Python 侧常量而非数据库 ENUM：
# 加值时不需要一次迁移，这与 ``collector_runs.status`` 取 String 是同一个理由。
LEAGUE_KINDS = ("war", "capital", "builder_base")
LABEL_KINDS = ("clan", "player")


class Location(Base):
    """地区。官方 ID 稳定，全球 = 32000000。"""

    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_country: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 官方对 Global 等非国家地区不发 countryCode
    country_code: Mapped[str | None] = mapped_column(String(10))


class LeagueTier(Base):
    """联赛层级（Bronze/Crystal/...），用于玩家详情页展示。"""

    __tablename__ = "league_tiers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    icon_urls: Mapped[dict | None] = mapped_column(JSONB)


class League(Base):
    """三种联赛合一，用 ``kind`` 区分。``id`` 在三种联赛间可能重复。

    主键是复合 ``(id, kind)``（Task 12 修正）：原定义只有 ``id`` 单列主键，与上面
    那句"id 可能重复"自相矛盾。后果是采集时 ``ON CONFLICT (id, kind)`` 找不到匹配
    的唯一索引直接报错；而若退而用 ``ON CONFLICT (id)``，一类联赛会静默覆盖
    另一类的行。
    """

    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    icon_urls: Mapped[dict | None] = mapped_column(JSONB)


class Label(Base):
    """两种标签合一，用 ``kind`` 区分。``id`` 在 clan/player 间可能重复。

    主键同样是复合 ``(id, kind)``，理由见 :class:`League`。
    """

    __tablename__ = "labels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    icon_urls: Mapped[dict | None] = mapped_column(JSONB)


class Season(Base):
    """赛季。主键为复合 ``(league_id, id)``。

    同一赛季号在不同联赛下是两条记录，因此不能只用 ``id`` 作主键。

    ``id`` 有两种格式：旧的 ``'2024-01'``，以及 2026-09 起的新格式
    ``'v2-2026-09-28T05:00:00Z'``（23 字符）—— 所以列宽是 64，别再压回 10。

    ``name`` / 时间列是 Task 12 补的：采集时官方会返回它们，丢掉就得再发一次
    请求才能显示。实测赛季元素只有 ``id``，这两个字段目前恒为 NULL。
    """

    __tablename__ = "seasons"

    league_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(100))
    start_time: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


# --------------------------------------------------------------------------- #
# 实体表（§5.2）
# --------------------------------------------------------------------------- #


class Clan(Base):
    """部落详情。

    ``location_id`` 与 ``war_league_id`` 等维表字段**只建索引不建外键**（§5.6）：
    采集顺序自由，维表未落库时部落也要能入库。反之，对 ``clan_members`` /
    ``clan_capitals`` 这类从属关系则必须建 FK 且 CASCADE。
    """

    __tablename__ = "clans"

    tag: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    clan_level: Mapped[int | None] = mapped_column(Integer)
    clan_points: Mapped[int | None] = mapped_column(Integer)
    clan_versus_points: Mapped[int | None] = mapped_column(Integer)
    required_trophies: Mapped[int | None] = mapped_column(Integer)
    war_frequency: Mapped[str | None] = mapped_column(String(20))
    war_win_streak: Mapped[int | None] = mapped_column(Integer)
    war_wins: Mapped[int | None] = mapped_column(Integer)
    war_ties: Mapped[int | None] = mapped_column(Integer)
    war_losses: Mapped[int | None] = mapped_column(Integer)
    is_war_log_public: Mapped[bool | None] = mapped_column(Boolean)
    member_count: Mapped[int | None] = mapped_column(Integer)
    # 维表字段：不建 FK（§5.6）
    location_id: Mapped[int | None] = mapped_column(Integer, index=True)
    war_league_id: Mapped[int | None] = mapped_column(Integer)
    capital_league_id: Mapped[int | None] = mapped_column(Integer)
    clan_builder_base_league_id: Mapped[int | None] = mapped_column(Integer)
    chat_language_id: Mapped[int | None] = mapped_column(Integer)
    badge_urls: Mapped[dict | None] = mapped_column(JSONB)
    labels: Mapped[list | None] = mapped_column(JSONB)
    # 官方返回但用途未定的原始字段统一存这里，避免加列就要一次迁移
    raw_extra: Mapped[dict | None] = mapped_column(JSONB)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_clans_war_league_id", "war_league_id"),)


class ClanCapital(Base):
    """部落都城，1:1。``districts`` 整段 JSONB。"""

    __tablename__ = "clan_capitals"

    clan_tag: Mapped[str] = mapped_column(
        String(10), ForeignKey("clans.tag", ondelete="CASCADE"), primary_key=True
    )
    capital_hall_level: Mapped[int | None] = mapped_column(Integer)
    districts: Mapped[list | None] = mapped_column(JSONB)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ClanMember(Base):
    """部落成员。主键 (clan_tag, player_tag)。

    对 ``players`` **不建 FK**：成员可能在玩家档案之前落库。
    """

    __tablename__ = "clan_members"

    clan_tag: Mapped[str] = mapped_column(
        String(10), ForeignKey("clans.tag", ondelete="CASCADE"), primary_key=True
    )
    player_tag: Mapped[str] = mapped_column(String(10), primary_key=True)
    player_name: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[str | None] = mapped_column(String(20))
    exp_level: Mapped[int | None] = mapped_column(Integer)
    trophies: Mapped[int | None] = mapped_column(Integer)
    builder_base_trophies: Mapped[int | None] = mapped_column(Integer)
    required_trophies: Mapped[int | None] = mapped_column(Integer)
    clan_rank: Mapped[int | None] = mapped_column(Integer)
    previous_clan_rank: Mapped[int | None] = mapped_column(Integer)
    donations: Mapped[int | None] = mapped_column(Integer)
    donations_received: Mapped[int | None] = mapped_column(Integer)
    # 维表字段：只建索引不建 FK
    league_tier_id: Mapped[int | None] = mapped_column(Integer, index=True)
    builder_base_league_id: Mapped[int | None] = mapped_column(Integer)
    player_house: Mapped[dict | None] = mapped_column(JSONB)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_clan_members_player_tag", "player_tag"),
        Index("ix_clan_members_league_tier_id", "league_tier_id"),
    )


class Player(Base):
    """玩家档案。

    ``clan_tag`` 指向 ``clans`` 但**不建 FK**：先拿到玩家、后拿到部落是常见顺序。
    """

    __tablename__ = "players"

    tag: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    exp_level: Mapped[int | None] = mapped_column(Integer)
    trophies: Mapped[int | None] = mapped_column(Integer)
    best_trophies: Mapped[int | None] = mapped_column(Integer)
    builder_base_trophies: Mapped[int | None] = mapped_column(Integer)
    required_trophies: Mapped[int | None] = mapped_column(Integer)
    war_stars: Mapped[int | None] = mapped_column(Integer)
    attack_wins: Mapped[int | None] = mapped_column(Integer)
    defense_wins: Mapped[int | None] = mapped_column(Integer)
    town_hall_level: Mapped[int | None] = mapped_column(Integer)
    builder_hall_level: Mapped[int | None] = mapped_column(Integer)
    versus_battle_wins: Mapped[int | None] = mapped_column(Integer)
    versus_trophies: Mapped[int | None] = mapped_column(Integer)
    role: Mapped[str | None] = mapped_column(String(20))
    donations: Mapped[int | None] = mapped_column(Integer)
    donations_received: Mapped[int | None] = mapped_column(Integer)
    # 无部落的玩家这两个字段为 NULL
    clan_tag: Mapped[str | None] = mapped_column(String(10), index=True)
    clan_name: Mapped[str | None] = mapped_column(String(100))
    # 维表字段：只建索引不建 FK
    league_tier_id: Mapped[int | None] = mapped_column(Integer, index=True)
    builder_base_league_id: Mapped[int | None] = mapped_column(Integer)
    town_hall_weapon_level: Mapped[int | None] = mapped_column(Integer)
    chat_language_id: Mapped[int | None] = mapped_column(Integer)
    achievements: Mapped[list | None] = mapped_column(JSONB)
    labels: Mapped[list | None] = mapped_column(JSONB)
    legend_statistics: Mapped[dict | None] = mapped_column(JSONB)
    raw_extra: Mapped[dict | None] = mapped_column(JSONB)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# --------------------------------------------------------------------------- #
# 运维与预留（§5.5）
# --------------------------------------------------------------------------- #


class User(Base):
    """二期账号功能的地基。本期无任何读写逻辑。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    openid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    unionid: Mapped[str | None] = mapped_column(String(64), unique=True)
    nickname: Mapped[str | None] = mapped_column(String(100))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class UserClanSubscription(Base):
    """用户订阅的部落，唯一约束在 (user_id, clan_tag) 上。"""

    __tablename__ = "user_clan_subscriptions"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    clan_tag: Mapped[str] = mapped_column(String(10), primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_user_clan_sub_clan_tag", "clan_tag"),
    )

# --------------------------------------------------------------------------- #
# 战场表（§5.3）
# --------------------------------------------------------------------------- #


class ClanWar(Base):
    """当前战，**单边视角**。

    官方的 currentwar 只能看到以我方为防守方的视角，不拼双边（§5.3）——
    试图合并两侧会得到自相矛盾的数据。故对手信息整体存 JSONB。
    """

    __tablename__ = "clan_wars"

    clan_tag: Mapped[str] = mapped_column(
        String(10), ForeignKey("clans.tag", ondelete="CASCADE"), primary_key=True
    )
    state: Mapped[str | None] = mapped_column(String(30))
    war_start_time: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    war_end_time: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    war_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    current_score: Mapped[int | None] = mapped_column(Integer)
    total_score: Mapped[int | None] = mapped_column(Integer)
    # 官方对象字段，整体存 JSONB：结构随游戏版本变，落列会频繁迁移
    attack: Mapped[dict | None] = mapped_column(JSONB)
    defense: Mapped[dict | None] = mapped_column(JSONB)
    attacker: Mapped[dict | None] = mapped_column(JSONB)
    defender: Mapped[dict | None] = mapped_column(JSONB)
    opponent: Mapped[dict | None] = mapped_column(JSONB)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ClanWarLog(Base):
    """战报，追加型。

    ``UNIQUE(clan_tag, end_time, result)`` 是必需的：采集会反复拉到同一批战报，
    没有这个约束库里会迅速膨胀出同一场战斗的几十份副本。
    """

    __tablename__ = "clan_war_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    clan_tag: Mapped[str] = mapped_column(
        String(10), ForeignKey("clans.tag", ondelete="CASCADE")
    )
    end_time: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result: Mapped[str] = mapped_column(String(10), nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    clan_score: Mapped[int | None] = mapped_column(Integer)
    opponent_score: Mapped[int | None] = mapped_column(Integer)
    clan_stars: Mapped[int | None] = mapped_column(Integer)
    opponent_stars: Mapped[int | None] = mapped_column(Integer)
    opponent: Mapped[dict | None] = mapped_column(JSONB)
    attacker: Mapped[dict | None] = mapped_column(JSONB)
    defender: Mapped[dict | None] = mapped_column(JSONB)
    stars: Mapped[dict | None] = mapped_column(JSONB)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("clan_tag", "end_time", "result", name="uq_warlog"),
        Index("ix_war_logs_clan_end", "clan_tag", "end_time"),
    )


class CwlLeagueGroup(Base):
    """CWL 联赛组，1:1。``rounds`` 整段 JSONB（结构随版本变）。"""

    __tablename__ = "cwl_league_groups"

    clan_tag: Mapped[str] = mapped_column(
        String(10), ForeignKey("clans.tag", ondelete="CASCADE"), primary_key=True
    )
    current_round: Mapped[int | None] = mapped_column(Integer)
    rounds: Mapped[list | None] = mapped_column(JSONB)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CwlWar(Base):
    """CWL 单场战斗。``war_tag`` 是官方给的全局唯一标识。"""

    __tablename__ = "cwl_wars"

    war_tag: Mapped[str] = mapped_column(String(40), primary_key=True)
    clan_tag: Mapped[str | None] = mapped_column(String(10), index=True)
    opponent_clan_tag: Mapped[str | None] = mapped_column(String(10), index=True)
    battle_status: Mapped[str | None] = mapped_column(String(30))
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CapitalRaidSeason(Base):
    """都城突袭赛季。"""

    __tablename__ = "capital_raid_seasons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_start: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    season_end: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CapitalRaidClan(Base):
    """赛季参赛部落，复合主键 (season_id, clan_tag)。

    对 seasons 有 FK + CASCADE（从属关系，§5.6）。
    """

    __tablename__ = "capital_raid_clans"

    season_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("capital_raid_seasons.id", ondelete="CASCADE"),
        primary_key=True,
    )
    clan_tag: Mapped[str] = mapped_column(String(10), primary_key=True)
    offensive_win_count: Mapped[int | None] = mapped_column(Integer)
    defensive_win_count: Mapped[int | None] = mapped_column(Integer)
    stars_earned: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_capital_raid_clans_clan_tag", "clan_tag"),)

# --------------------------------------------------------------------------- #
# 排行榜（§5.4）
# --------------------------------------------------------------------------- #


class Ranking(Base):
    """6 类榜单合并为一张表（§5.4）。

    合并的理由：6 种口径的 upsert 与查询逻辑相同，拆表要写 6 遍，且新增榜单类型
    就得新增一张表。

    **刷新策略是「按 scope 全量替换」而不是逐条 upsert** —— 见
    ``app/collector/rankings_service.py``。逐条 upsert 会让已掉榜的条目永久残留，
    用户看到的是一份"半年前的榜单 + 今天的新增"，而且 API 返回 200，没有报错。

    ``location_id`` / ``league_id`` / ``season_id`` **不建外键**（§5.6）：维表会被
    重新导入，业务表不该被 FK 绑死。

    注意 UNIQUE 在这里**不是**万能的去重保证：PostgreSQL 认为 NULL 与 NULL 不相等，
    而地区榜的 ``league_id``/``season_id`` 恒为 NULL，该约束在地区榜上退化成允许重复。
    真正的去重必须发生在入库前（见 service 里的 tag 归一化）。
    """

    __tablename__ = "rankings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    # 地区榜时非空；赛季榜时为 NULL
    location_id: Mapped[int | None] = mapped_column(Integer, index=True)
    # season_players 时非空
    league_id: Mapped[int | None] = mapped_column(Integer, index=True)
    # 赛季 id 有两种格式（``2024-01`` / ``v2-2026-09-28T05:00:00Z``），列宽 64
    season_id: Mapped[str | None] = mapped_column(String(64), index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_rank: Mapped[int | None] = mapped_column(Integer)
    # 都城榜没有 tag，只有 name —— 故可空
    tag: Mapped[str | None] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # 玩家榜带的部落信息
    clan_tag: Mapped[str | None] = mapped_column(String(10))
    clan_name: Mapped[str | None] = mapped_column(String(100))
    clan_level: Mapped[int | None] = mapped_column(Integer)
    trophies: Mapped[int | None] = mapped_column(Integer)
    builder_base_trophies: Mapped[int | None] = mapped_column(Integer)
    points: Mapped[int | None] = mapped_column(Integer)
    members: Mapped[int | None] = mapped_column(Integer)
    exp_level: Mapped[int | None] = mapped_column(Integer)
    attack_wins: Mapped[int | None] = mapped_column(Integer)
    defense_wins: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "kind", "location_id", "league_id", "season_id", "tag", name="uq_ranking"
        ),
        Index("ix_rankings_kind_location_rank", "kind", "location_id", "rank"),
        Index("ix_rankings_kind_league_season_rank", "kind", "league_id", "season_id", "rank"),
    )

class CollectorRun(Base):
    """一次采集运行的记录（§5.5）。

    存在的理由只有一个：**让静默的失败变响亮**。采集是定时任务，失败了没人会
    收到通知，只能靠这张表事后发现"榜单三天没更新"。

    因此 ``status`` 用 ``String`` 而不是数据库 ENUM：加一个状态值不需要迁移。
    Python 侧用 :class:`app.collector.service.RunStatus` 约束取值。

    ``started_at`` 落库后**立即 commit**，然后才开始干活。这样进程被 kill 时
    库里会留下一条永远停在 ``running`` 的记录 —— 那正是"卡住了"的信号。
    """

    __tablename__ = "collector_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    items_total: Mapped[int | None] = mapped_column(Integer)
    items_ok: Mapped[int | None] = mapped_column(Integer)
    items_failed: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (Index("ix_collector_runs_job_started", "job_name", "started_at"),)

# --------------------------------------------------------------------------- #
# 升级数据（§5.5）
# --------------------------------------------------------------------------- #


class UpgradeCategory(StrEnum):
    """升级条目类别。

    用 ``StrEnum`` 而非 DB ENUM：加类别时不需要迁移。
    """

    building = "building"
    troop = "troop"
    spell = "spell"
    hero = "hero"
    equipment = "equipment"


class UpgradeItem(Base):
    """升级条目。建筑/兵种/法术/英雄/装备共用一张表。

    合并理由：三类资源成本字段结构一致（资源 + 时长 + 前置等级），拆表要写多遍。

    ``level`` 的语义是「**从** level 升到 level+1」—— 差一格会让用户算出
    完全错误的成本，且没有任何报错。这是全项目最容易搞错的一处约定。

    ``name_zh`` 与 ``builder_count`` 由导入阶段留空（不猜翻译），后续人工或接口层
    填充。导入的 upsert **不覆盖** 这两列，免得重跑冲掉人工标注。
    """

    __tablename__ = "upgrade_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    name_zh: Mapped[str | None] = mapped_column(String(100))
    village: Mapped[str] = mapped_column(String(20), nullable=False, default="home")
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    # 大数：某些英雄升级的暗元素成本超过 32 位上限的上四分之一
    gold: Mapped[int | None] = mapped_column(BigInteger)
    elixir: Mapped[int | None] = mapped_column(BigInteger)
    dark_elixir: Mapped[int | None] = mapped_column(BigInteger)
    build_time_seconds: Mapped[int | None] = mapped_column(Integer)
    builder_count: Mapped[int | None] = mapped_column(Integer)
    required_townhall_level: Mapped[int | None] = mapped_column(Integer)
    required_lab_level: Mapped[int | None] = mapped_column(Integer)
    required_builder_base_level: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("category", "name", "village", "level", name="uq_upgrade_item"),
        # 查"某单位全部等级"是最高频的访问路径
        Index("ix_upgrade_items_lookup", "category", "name", "village"),
        Index("ix_upgrade_items_category", "category", "name_zh"),
    )


class UpgradeRoute(Base):
    """升级路线：由大营到某项的路径集合。"""

    __tablename__ = "upgrade_routes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    name_zh: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # relationship 只服务于读取。步骤是从属关系，删路线连带删步骤（FK CASCADE）；
    # lazy="selectin" 让详情接口一次取回，避免 N+1 —— 一条路线几十步，
    # 懒加载就是几十次查询。
    steps: Mapped[list["UpgradeRouteStep"]] = relationship(
        back_populates="route",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="UpgradeRouteStep.step_order",
    )


class UpgradeRouteStep(Base):
    """路线上的一步。

    对 ``upgrade_routes`` 有 FK + CASCADE：从属关系（§5.6）。
    """

    __tablename__ = "upgrade_route_steps"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    route_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("upgrade_routes.id", ondelete="CASCADE"),
        index=True,
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    item_id: Mapped[int | None] = mapped_column(
        ForeignKey("upgrade_items.id", ondelete="CASCADE"), index=True
    )
    target_level: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    # 展开成条目快照，前端不必为每个步骤再发一次请求。
    # selectin 而非 joined：一对多下 joined 会把主表行重复成笛卡尔积，
    # 分页时 total 也会跟着错。
    item: Mapped["UpgradeItem | None"] = relationship(lazy="selectin")

    route: Mapped["UpgradeRoute"] = relationship(back_populates="steps")

    __table_args__ = (
        UniqueConstraint("route_id", "step_order", name="uq_route_step"),
    )

class Announcement(Base):
    """公告。

    草稿（`is_published=False`）对外完全不可见 —— 列表与按 id 详情都要挡，
    否则草稿等于公开。审核与录入在 SQLAdmin 后台（Task 19）。
    """

    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # notice（通知）/ maintenance（维护）/ event（活动）
    category: Mapped[str] = mapped_column(String(30), nullable=False, default="notice")
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 可空：草稿还没到发布时间
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        # 首页查询：只取已发布，按置顶 + 时间排
        Index("ix_announcements_published", "is_published", "is_pinned", "published_at"),
        Index("ix_announcements_category", "category"),
    )


class Submission(Base):
    """用户投稿（一期只收阵容与阵型）。

    ``status`` 用 String + Python StrEnum，加状态值无需迁移。
    ``payload`` 是 JSONB —— 形状随投稿类型变化，落列会频繁迁移。
    """

    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # army_composition | base_layout
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # pending | approved | rejected。**列上带 server_default**，
    # 靠应用层填默认值的话，任何绕过 ORM 的插入路径都会拿到 NULL。
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )
    reject_reason: Mapped[str | None] = mapped_column(Text)
    # 投稿人。一期不做账号（users 表已留地基），故可空
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(100))
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        # 后台工作队列：只看待审的，按时间正序
        Index("ix_submissions_status_created", "status", "created_at"),
    )


class ArmyComposition(Base):
    """阵容（一期只读展示）。数据来自投稿审核或后台录入。"""

    __tablename__ = "army_compositions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    title_zh: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    th_level: Mapped[int | None] = mapped_column(Integer, index=True)
    # 来源三件套：URL + 站点名 + 内容哈希。二期按 copy_count 排热度时，
    # 需要知道同一份内容被抄了多少次、抄自哪里
    source_url: Mapped[str | None] = mapped_column(Text)
    source_site: Mapped[str | None] = mapped_column(String(50))
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    copy_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    submission_id: Mapped[int | None] = mapped_column(
        ForeignKey("submissions.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    items: Mapped[list["ArmyCompositionItem"]] = relationship(
        back_populates="composition",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="ArmyCompositionItem.position",
    )


class ArmyCompositionItem(Base):
    """阵容里的一项。对阵容是从属关系，删阵容连带删（§5.6）。"""

    __tablename__ = "army_composition_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    composition_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("army_compositions.id", ondelete="CASCADE"),
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str | None] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    level: Mapped[int | None] = mapped_column(Integer)
    quantity: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    composition: Mapped["ArmyComposition"] = relationship(back_populates="items")

    __table_args__ = (
        UniqueConstraint("composition_id", "position", name="uq_composition_position"),
    )


class BaseLayout(Base):
    """阵型。一期只存链接或图片路径，不做图片托管。"""

    __tablename__ = "base_layouts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    title_zh: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    th_level: Mapped[int | None] = mapped_column(Integer, index=True)
    # 链接与图片至少有一个，由投稿校验与审核共同保证
    layout_link: Mapped[str | None] = mapped_column(Text)
    image_path: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_site: Mapped[str | None] = mapped_column(String(50))
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    copy_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    submission_id: Mapped[int | None] = mapped_column(
        ForeignKey("submissions.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


# --------------------------------------------------------------------------- #
# War Report 数据（§5.3.2）
# --------------------------------------------------------------------------- #


class WarReportArmy(Base):
    """War Report 阵容（配兵）使用统计，**每次都整表替换**。

    数据来自第三方 https://api.warreport.app 的 ``/armies``，与
    :class:`ArmyComposition` **不是一回事**：后者是投稿/后台录入的内容
    （标题、描述、子项），这里存的是"某种配兵被多少人用过、平均几星几拆"。
    混用会让两类数据互相污染。

    刷新策略与排行榜同源（先 ``DELETE`` 全表再批量 ``INSERT``，同一事务），所以
    ``canonical_key`` 的唯一约束**不是**给 upsert 用的 —— 它挡的是上游同一次响应
    里出现两条同 key 的脏行。

    约束名必须显式写出且与迁移 0012 逐字一致：``Base`` 没有配
    ``naming_convention``，写成 ``unique=True`` 会落成 Postgres 自动名
    ``warreport_armies_canonical_key_key``，此后 ``--autogenerate`` 会反复生成
    「删约束 / 建约束」。
    """

    __tablename__ = "warreport_armies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 上游顺序即使用率降序；它本身不给序号，由 job 按 1 起连续编号（过滤后再编）
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    canonical_key: Mapped[str] = mapped_column(Text, nullable=False)
    army_share_code: Mapped[str] = mapped_column(Text, nullable=False)
    army_link: Mapped[str] = mapped_column(Text, nullable=False)
    player_count: Mapped[int] = mapped_column(Integer, nullable=False)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False)
    percentage: Mapped[float] = mapped_column(Float, nullable=False)
    average_stars: Mapped[float] = mapped_column(Float, nullable=False)
    average_destruction: Mapped[float] = mapped_column(Float, nullable=False)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("canonical_key", name="uq_warreport_armies_canonical_key"),
        Index("ix_warreport_armies_position", "position"),
    )
