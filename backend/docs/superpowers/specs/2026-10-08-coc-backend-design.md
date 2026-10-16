# COC 小程序后端 —— 设计规格

- **日期**：2026-10-08
- **状态**：待用户审阅
- **文档位置**：`docs/superpowers/specs/2026-10-08-coc-backend-design.md`

---

## 1. 目标与范围

为微信小程序 `F:\Python_file\MiniProgram\COC` 提供后端服务。核心流程：调用 Supercell 官方 COC API 抓取游戏数据 → 整理入 PostgreSQL → 接收小程序请求并返回；此外提供后台管理器用于人工维护站点无法自动获取的内容。

部署目标为单台 Linux 服务器（Docker Compose + nginx + HTTPS）。

### 1.1 关键约束

| 约束 | 内容 |
| --- | --- |
| 官方 API 只读 | Supercell API 无法写入任何游戏数据 |
| Token + IP 白名单 | Token 强绑公网出口 IP，IP 变更会导致全部调用 403 |
| 网络位置 | 域名已备案 → 服务器位于中国大陆 → 海外站点不可达 |
| 单管理员 | 后台仅一个管理员账号，不做角色权限模型 |
| 速率限制 | 官方约 10 req/s，社区安全阈值 8 req/s |

### 1.2 范围外（明确不做）

- 爬虫模块（一期、二期均不做；降级为独立可选项目，详见 §10.4）
- 用户注册/登录/收藏等账号功能（仅预留表结构，见 §5.5）
- 多副本水平扩展（架构预留，部署保持单副本）
- 建筑升级等级明细表（仅做升级路线表，见 §10.3）

---

## 2. 小程序页签与阶段划分

| 页签 | 功能 | 数据来源 | 阶段 |
| --- | --- | --- | --- |
| 查询 | 查玩家、查部落、战报、当前战、CWL | API 管道自动 | 一期 |
| 查询 → 排行榜 | 6 类榜单 | API 管道自动 | 一期 |
| 我的 | 升级数据（路线 + 条目明细） | 数据种子导入 | 一期 |
| 我的 | 公告主题 | 后台人工录入 | 一期 |
| 阵容 | 本月传奇玩家热门阵容，可复制 | 后台录入 + 投稿审核 | 二期 |
| 阵型 | 图片 + 可复制阵型链接 | 后台录入 + 投稿审核 | 二期 |

**一期即建投稿入口**：`submissions` 表与投稿接口在一期上线，用户提交的数据经后台审核后自动转为正式的 `army_compositions` / `base_layouts` 记录。这样二期页签上线时内容已积累，而非从零开始。

**「热门」的排序依据**：官方 API 不提供任何配兵信息，因此热度只能来自站内行为。用户点击「复制」时后端 `copy_count += 1`，榜单按本月新建 + `copy_count` 降序。复制动作必须是真实接口调用，不能是前端本地行为。

---

## 3. 架构

### 3.1 进程模型

单进程一体：uvicorn 单 worker + 同进程 APScheduler 调度器。选择依据是当前流量规模下无需 Redis，且进程内令牌桶限流最精确。

为将来拆分预留：`APP_ROLE` 环境变量控制启动角色（`all` / `api` / `collector`）；`RateLimiter` 抽象为接口，内存实现将来可替换为 Redis 实现而无须改动装配代码。

### 3.2 目录结构

```
app/
├─ main.py              FastAPI 工厂 + lifespan（按 APP_ROLE 启停调度器）
├─ config.py            pydantic-settings，全部配置走环境变量
├─ cli.py               运维命令（import-game-data、建管理员、手动触发采集）
├─ api/
│  ├─ deps.py           依赖注入：DB session、CocClient
│  ├─ schemas.py        Pydantic 响应模型
│  └─ routes/
│     ├─ clans.py       搜索/详情/成员/战报/当前战/CWL
│     ├─ players.py     档案/verifytoken
│     ├─ rankings.py    6 类榜单 + 地区 + 联赛
│     ├─ upgrade.py     升级路线与条目
│     ├─ content.py     公告
│     ├─ submissions.py 投稿
│     ├─ admin.py       SQLAdmin 挂载
│     └─ system.py      /healthz /readyz /meta/freshness
├─ coc/                 唯一与 Supercell 耦合的模块
│  ├─ client.py         CocClient：httpx + 令牌桶 + 指数退避
│  ├─ ratelimit.py      RateLimiter 接口 + MemoryRateLimiter
│  ├─ endpoints.py      官方接口薄封装，返回原始 dict
│  ├─ errors.py         CocError 层次
│  └─ mappers.py        官方响应 dict → ORM
├─ collector/           采集编排，不依赖 FastAPI
│  ├─ scheduler.py      APScheduler 组装与错峰
│  ├─ service.py        编排：取数 → 映射 → upsert
│  └─ jobs/             static_data / rankings / leagues / seasons
├─ content/             内容管理业务逻辑
│  ├─ game_data.py      npm 包解析 → 升级条目导入
│  └─ submissions.py    投稿审核流转
├─ cache/
│  ├─ readthrough.py    读时旁路
│  └─ ttl.py            TTL 表
└─ db/
    ├─ base.py          DeclarativeBase、session factory
    ├─ models.py        ORM 模型
    └─ migrations/      Alembic
```

### 3.3 隔离点

1. `coc/` 是唯一外部世界。Supercell 改字段、换限流规则、Token 轮换只影响此目录。
2. `collector/` 不依赖 FastAPI，可在任意进程/时机被调用；将来拆为独立容器时该目录无需改动。
3. `api/routes/` 不直接使用 httpx，只做「参数校验 → 调用 cache 层 → 序列化」。

---

## 4. 数据流

### 4.1 读时旁路（按需资源）

```
GET /api/v1/clans/%232PP
 ├─ 查库：命中 且 fetched_at + TTL > now？
 │    ├─ 是 ──► 200, meta.cache=HIT
 │    └─ 否 ↓
 ├─ CocClient.get_clan()
 │    ├─ 成功 → mappers → upsert ──► 200, meta.cache=MISS
 │    ├─ 429/5xx/超时 → 退避重试 3 次；仍失败：
 │    │      有旧数据 ──► 200, meta.cache=STALE
 │    │      无旧数据 ──► 502
 │    └─ 业务错误/403 ──► 直接转对应 HTTP 码，不重试、不降级
```

### 4.2 定时批量（看板资源）

各 job 错峰触发，避免整点同时请求。流程：遍历资源清单（如 `locations` 表中 `is_country = true` 的地区）→ CocClient 串行抓取（令牌桶统一限速）→ upsert → 写入 `collector_runs`。

### 4.3 TTL 表

定义于 `cache/ttl.py`，集中管理。

| 资源 | TTL | 依据 |
| --- | --- | --- |
| clan 详情 / members | 300 s | 官方文档建议 1–5 min |
| currentwar | 120 s | 官方文档建议 1–2 min，战斗中实时变化 |
| warlog | 600 s | 追加型，平时不变 |
| CWL leaguegroup | 600 s | — |
| player 档案 | 300 s | — |
| leaguetiers / locations / labels | 86 400 s | 静态字典 |
| warleagues / capitalleagues / builderbaseleagues | 3 600 s | — |
| season 排名 / 地区排行榜 | 21 600 s | 名次变动不频繁 |
| goldpass current | 3 600 s | — |

### 4.4 限流

进程内令牌桶，默认 8 req/s（官方约 10 req/s 的安全阈值）。配合单请求最多 3 次指数退避。

---

## 5. 数据模型

### 5.1 维表

| 表 | 主键 | 说明 |
| --- | --- | --- |
| `locations` | `id` int | 地区，官方 ID 稳定（全球 = `32000000`） |
| `league_tiers` | `id` int | 联赛层级，`icon_urls` JSONB |
| `leagues` | `id` int | 3 种联赛合一，`kind` ∈ `war`/`capital`/`builder_base` |
| `labels` | `id` int | 2 种标签合一，`kind` ∈ `clan`/`player` |
| `seasons` | `(league_id, id)` | 赛季，`id` 形如 `'2024-01'` |

### 5.2 实体表

| 表 | 主键 | 要点 |
| --- | --- | --- |
| `clans` | `tag` | 部落详情全字段 + `member_count` + `fetched_at` |
| `clan_capitals` | `clan_tag` | 1:1，`districts` JSONB |
| `clan_members` | `(clan_tag, player_tag)` | 含 `role`/`clan_rank`/`donations`/`player_house` JSONB；另建 `player_tag` 索引支持反查 |
| `players` | `tag` | 档案 + `achievements`/`labels`/`legend_statistics` JSONB |

### 5.3 战场表

| 表 | 主键 | 说明 |
| --- | --- | --- |
| `clan_wars` | `clan_tag` | 单边视角；`currentwar` 只能看到以我方为防守方的视角，不拼双边 |
| `clan_war_logs` | 自增 id | `UNIQUE(clan_tag, end_time, result)` 防重复写入 |
| `cwl_league_groups` | `clan_tag` | `rounds` 整段 JSONB |
| `cwl_wars` | `war_tag` | — |
| `capital_raid_seasons` | `id` | 都城突袭赛季 |
| `capital_raid_clans` | `(season_id, clan_tag)` | FK 到赛季，`ON DELETE CASCADE` |

### 5.4 排行榜统一表

6 类榜单（5 类地区榜 + 1 类赛季榜）合并为一张 `rankings` 表：

```
rankings(
  id, kind,                -- clans|players|capitals|clans_builder_base
                           -- |players_builder_base|season_players
  location_id,             -- 地区榜时非空
  league_id, season_id,    -- season_players 时非空
  rank, previous_rank,
  tag, name,
  clan_tag, clan_name, clan_level,
  trophies, builder_base_trophies, points,
  members, exp_level, attack_wins, defense_wins,
  fetched_at
)
UNIQUE(kind, location_id, league_id, season_id, tag)
INDEX(kind, location_id, rank)
INDEX(kind, league_id, season_id, rank)
```

合并理由：6 种口径的 upsert 与查询逻辑相同，拆表需写 6 遍且新增榜单类型需新增表。

**刷新策略：按 scope 全量替换**。刷 `location_id = X, kind = 'clans'` 时执行 `DELETE ... WHERE` + 批量 `INSERT`，同一事务内完成。避免逐条 upsert 导致「已掉榜条目永久残留」的经典缺陷。

### 5.5 内容管理表

**升级条目**（建筑/兵种/法术/英雄/装备共用一张表）

```
upgrade_items(
  id, category,             -- building|troop|spell|hero|equipment
  name, name_zh,
  village,                  -- home|builderBase
  level,                    -- 表示从 level 升到 level+1
  gold, elixir, dark_elixir,
  build_time_seconds, builder_count,
  required_townhall_level,
  required_lab_level,
  required_builder_base_level,
  notes,
  UNIQUE(category, name, village, level)
)
```

合并理由：三类资源成本字段结构一致（资源 + 时长 + 前置等级），仅 `required_lab_level` 等对建筑为空。

`name_zh` 与 `builder_count` 在源数据集中不存在，导入时置 `NULL`，由后台人工补齐（见 §10.3）。`category` 保留 `building` 取值以备将来数据可得，但一期不导入该类数据。

**升级路线**

```
upgrade_routes(
  id, current_th, target_th, summary,
  total_gold, total_elixir, total_dark, total_build_seconds,
  source_url, source_site, content_hash, created_at
)
upgrade_route_steps(
  id, route_id FK→upgrade_routes ON DELETE CASCADE,
  category, target_name, target_level, sort_order
)
```

**公告**

```
announcements(
  id, title, body,          -- body 支持 Markdown
  category,                 -- notice|update|event|maintenance
  cover_image,
  is_pinned, is_published,
  published_at, created_at, updated_at
)
```

**阵容（二期）**

```
army_compositions(
  id, title, description,
  th_level, attack_type, season_id, is_current_season,
  author_clan_tag, author_player_tag, author_player_name,
  copy_count, is_published, created_at, published_at,
  source_url, source_site, content_hash
)
army_composition_items(
  id, composition_id FK ON DELETE CASCADE,
  category,                 -- troop|spell|hero|hero_equipment
  name, quantity, level, sort_order
)
```

**阵型（二期）**

```
base_layouts(
  id, title, description,
  th_level, target_type,    -- attack|defense
  image_path, layout_link,
  copy_count, is_published, created_at, published_at,
  source_url, source_site, content_hash
)
```

**投稿（一期）**

```
submissions(
  id, type,                 -- army_composition|base_layout
  title, description, payload JSONB,
  contact,                  -- 用户联系方式，可空
  status,                   -- pending|approved|rejected
  reject_reason,
  reviewed_at, created_at
)
```

审核通过时，由 `content/submissions.py` 将 `payload` 转换为对应正式记录，并回填 `source_site = 'user_submission'`。

**运维与预留**

```
collector_runs(
  id, job_name, started_at, finished_at,
  status,                   -- running|success|partial|failed
  items_total, items_ok, items_failed, error JSONB
)
users(id, openid UNIQUE, unionid, nickname, avatar_url, created_at, last_login_at)
user_clan_subscriptions(user_id, clan_tag, created_at, UNIQUE(user_id, clan_tag))
```

### 5.6 外键策略

业务表**不建外键约束到维表**（`clans.location_id`、`clan_members.league_tier_id` 等只建索引）。原因：批量采集时「先刷部落（引用未入库的联赛）」与「先刷联赛」的顺序必须自由，外键会让插入顺序成为隐式约束，导致个别 FK 违规使整批回滚。官方 ID 本身稳定，`mappers.py` 保证引用有效。

真正的从属关系仍建 FK：`clan_members.clan_tag → clans.tag`、`upgrade_route_steps.route_id`、`army_composition_items.composition_id`、`capital_raid_clans.season_id`，均 `ON DELETE CASCADE`。

---

## 6. API 契约

**Base URL**：`https://{域名}/api/v1`

### 6.1 统一响应体

成功：

```json
{
  "data": {},
  "meta": {
    "cache": "HIT | MISS | STALE",
    "fetched_at": "2026-10-08T10:00:00Z",
    "age_seconds": 42,
    "ttl_seconds": 300
  }
}
```

`cache = "STALE"` 表示回源失败但库中有旧数据，此时返回 HTTP 200，前端据此提示数据可能过期。

失败：

```json
{
  "error": {
    "code": "CLAN_NOT_FOUND",
    "message": "部落标签不存在或已失效",
    "upstream_reason": "notFound"
  }
}
```

### 6.2 对外错误码

| HTTP | code | 来源 |
| --- | --- | --- |
| 400 | `INVALID_TAG` | 标签格式非 `#XXX` |
| 404 | `CLAN_NOT_FOUND` / `PLAYER_NOT_FOUND` | 官方 `notFound` |
| 404 | `CLAN_NOT_IN_WAR` | 官方 `notInWar`（业务态） |
| 403 | `WARLOG_PRIVATE` | 官方 `privateWarLog`（业务态） |
| 429 | `RATE_LIMITED` | 自身限流 |
| 502 | `UPSTREAM_THROTTLED` | 官方 429 且无可退缓存 |
| 502 | `UPSTREAM_UNAVAILABLE` | 官方 5xx 或网络失败 |
| 503 | `SERVICE_UNAVAILABLE` | 自身不可用 |

官方 6 种 `reason` 被收敛为上述稳定业务码，官方字段变更不影响前端。

### 6.3 分页

对外统一 `page` / `page_size`，默认 20，上限 50。官方 base64 游标仅在采集层内部使用。

### 6.4 一期接口

**查询**

```
GET  /clans/search?name=&locationId=&limit=
GET  /clans/{tag}
GET  /clans/{tag}/members
GET  /clans/{tag}/warlog
GET  /clans/{tag}/currentwar
GET  /clans/{tag}/cwl
GET  /players/{tag}
POST /players/{tag}/verifytoken
```

**排行榜**

```
GET  /locations
GET  /rankings/clans?locationId=
GET  /rankings/players?locationId=
GET  /rankings/capitals?locationId=
GET  /rankings/clans_builder_base?locationId=
GET  /rankings/players_builder_base?locationId=
GET  /rankings/season/{leagueId}/{seasonId}
GET  /leagues/{kind}
```

**我的**

```
GET  /upgrade/routes?from_th=&to_th=
GET  /upgrade/routes/{id}
GET  /upgrade/items?category=&village=&name=
GET  /announcements?category=
GET  /announcements/{id}
```

**投稿**

```
POST /submissions
GET  /submissions/{id}
```

**系统**

```
GET  /healthz
GET  /readyz
GET  /meta/freshness
```

**后台**：`/admin`（SQLAdmin）

### 6.5 投稿数据结构

```jsonc
POST /api/v1/submissions
{
  "type": "army_composition",
  "title": "TH16猪流速推",
  "description": "电龙+冰车+猪，注意雷电法杖位置",
  "payload": {
    "th_level": 16,
    "items": [{"category": "troop", "name": "Hog Rider", "quantity": 30, "level": 14}],
    "image_url": null,
    "layout_link": null
  },
  "contact": null
}
```

响应：`201 {"data": {"id": 123, "status": "pending"}}`

### 6.6 对外限流

一期无 openid，按 IP 限流 60 次/分钟，nginx 层与应用层双重实施。阈值偏宽，因运营商 NAT 会导致多用户共享出口 IP，避免误伤。接入 openid 后改为按 openid 限流。

---

## 7. 错误处理与限流

### 7.1 异常层次

```
CocError
├─ CocBusinessError     业务态，不重试、不进告警
│   ├─ ClanNotFound / PlayerNotFound
│   ├─ NotInWar
│   └─ WarLogPrivate
├─ CocFaultError        故障态，可重试
│   ├─ CocThrottled       官方 429
│   ├─ CocUpstreamError   官方 5xx
│   └─ CocTimeout
├─ CocAccessDenied      403，不重试，立即告警
└─ CocProtocolError     响应结构异常，记录原始响应并告警
```

`CocAccessDenied`（`accessDenied.invalidIp`）单独摘出的原因：该错误意味着服务器公网 IP 变更或白名单未配置，会导致全部官方调用失败。若不单独告警，表现为大量 404 与空数据，排查方向完全偏离。

### 7.2 重试策略

| 异常 | 重试次数 | 退避 |
| --- | --- | --- |
| `CocThrottled` / `CocUpstreamError` / `CocTimeout` | 3 | 1 s → 2 s → 4 s |
| `CocBusinessError` | 0 | — |
| `CocAccessDenied` | 0 + 告警 | — |

### 7.3 日志与可观测

结构化 JSON 日志，字段含 `request_id`、`resource`、`tag`、`cache_status`、`latency_ms`、`outcome`。

`outcome` 取值：`hit` / `miss` / `stale` / `error_business` / `error_fault` / `error_access`。

告警触发：`CocAccessDenied` 出现即告警；429 连续 5 次告警；`collector_runs.status = 'failed'` 告警。

---

## 8. 部署与配置

### 8.1 编排

```yaml
services:
  api:        # FastAPI + 调度器，单副本，不暴露端口
  postgres:   # 仅容器网络可达
  nginx:      # HTTPS 入口 + 静态文件托管
volumes:
  media:      # 阵型与公告图片
```

nginx 路由：`/api` → api · `/admin` → api · `/media/` → volume 静态目录 · 其余 404。

图片存储采用本地 Docker volume，由 nginx 直接托管静态文件，不引入对象存储。备份通过卷打包脚本完成。

### 8.2 配置项

`.env.example` 入库，`.env` 永不入库。

```
COC_API_TOKEN=            # Supercell JWT
DATABASE_URL=             # postgresql+asyncpg://...
APP_ROLE=all              # all | api | collector
COC_RATE_LIMIT=8          # 每秒请求数
COC_TIMEOUT=15
MEDIA_ROOT=/data/media
PUBLIC_BASE_URL=https://{域名}
LOG_LEVEL=INFO
```

### 8.3 上线步骤

1. 服务器安装 Docker + Compose
2. 拉取代码 → `cp .env.example .env` → 填入 Token 与数据库密码
3. 启动 postgres → `alembic upgrade head`
4. `python -m app.cli import-game-data` 导入升级数据种子
5. 创建管理员账号
6. 启动 api 与 nginx
7. 申请 Let's Encrypt 证书并配置自动续期
8. 小程序后台将域名加入「request 合法域名」

### 8.4 备份

`pg_dump` 每日 cron，保留 14 天；`media` 卷每日 tar 打包。备份存放于服务器之外的存储。

---

## 9. 测试策略

### 9.1 单元测试（主力）

- `ratelimit` —— 令牌桶速率正确、退避时序符合预期
- `mappers` —— 官方响应 → ORM，字段缺失或新增均不报错
- `readthrough` —— 命中 / 未命中 / 回源失败降级为 STALE / 业务错误不降级
- `rankings` 刷新 —— 全量替换后已掉榜条目不残留

### 9.2 契约测试

- CocClient 使用 `httpx.MockTransport` 打桩，验证 429 会重试、403 不重试、超时按预期处理
- FastAPI 路由响应体以 OpenAPI schema 断言
- 若干真实 API 响应样本保存于 `tests/fixtures/` 作为 mock 数据源

### 9.3 集成测试

本地 PostgreSQL → `alembic upgrade` → 导入种子 → 冒烟跑通主要接口。

### 9.4 硬性规定

CI 中不得调用真实 Supercell API（会消耗速率额度、依赖外网、Token 过期会导致 CI 随机失败）。真实 API 调用仅在手动触发的冒烟测试中执行一次，用于验证 Token 与 IP 白名单。

---

## 10. 关键决策记录

### 10.1 架构选型

**已采纳**：单进程一体（uvicorn 单 worker + 同进程 APScheduler）。

**已否决**：
- 双进程 + Redis —— v1 流量规模撑不起该组件成本
- api / worker / beat 三件套 —— 明显过度设计

保留 `APP_ROLE` 与 `RateLimiter` 接口作为迁移路径。

### 10.2 技术栈

FastAPI + SQLAlchemy 2.0 (async) + Alembic + PostgreSQL + APScheduler + SQLAdmin + httpx + pytest。

曾考虑 Django + DRF，其自带 admin 可减少内容管理后台代码，但用户选择保留 FastAPI 生态。

### 10.3 数据来源策略

| 数据 | 来源 |
| --- | --- |
| 玩家/部落/战报/榜单/联赛 | Supercell 官方 API |
| 兵种/法术/英雄/装备升级数据 | `clashofclans.js@4.0.5` npm 包（MIT） |
| 升级路线（TH N → N+1） | 后台人工录入 |
| 建筑升级等级明细 | **不做**（数据源不可得，见 10.4） |
| 公告 | 后台人工录入 |
| 阵容/阵型 | 后台录入 + 用户投稿审核 |

#### 升级数据导入机制

`app.cli import-game-data` 的行为：

1. 从 `https://registry.npmjs.org/clashofclans.js` 获取元信息，定位 `latest` 版本
2. 下载 tarball，解压，读取 `package/dist/util/raw.json`
3. 遍历 `RAW_UNITS`，按 `category` 映射为 `troop`/`spell`/`hero`/`equipment`（`RAW_SUPER_UNITS` 的 17 个超级兵种为一次性升级，无等级数组，**不导入**）
4. 对每个单位，按 `upgrade.cost[]` 与 `upgrade.time[]` 的索引生成每级一行；索引 `i` 对应从 `level = i + 1` 升到 `level = i + 2`
5. `unlock.hall` → `required_townhall_level`，`unlock.buildingLevel` → `required_builder_base_level`（仅当 `village = builderBase`）
6. 资源类型由 `upgrade.resource` 映射到 `gold` / `elixir` / `dark_elixir` 三列之一
7. `name_zh` 与 `builder_count` 置 `NULL`
8. 幂等：以 `UNIQUE(category, name, village, level)` 做 upsert，重复执行安全

实现要点：全程纯 Python（`urllib` + `tarfile`），**服务器不需要安装 Node.js 或 npm**。tarball 可选地缓存到本地以支持离线重跑。

#### 人工补齐流程

导入后进入一次性的数据补齐工作，全部通过后台完成，无需写代码：

- `name_zh` —— 147 个单位的中文名，可在 SQLAdmin 列表页直接编辑
- `builder_count` —— 升级所需工人数量
- `upgrade_routes` —— TH 升级路线及其 `upgrade_route_steps`

补齐进度可通过 `GET /meta/freshness` 与 `collector_runs` 之外的独立查询掌握：`SELECT count(*) FROM upgrade_items WHERE name_zh IS NULL`。

### 10.4 爬虫可行性验证结论

一次性调查，已完成：

1. **CocClient 直连官方 API 正常** —— httpx 0.28.1 直连 `api.clashofclans.com` 返回预期 403，耗时 1.4 s。TLS 指纹拦截仅影响营销站 `www.clashofclans.com`，不影响 API 域名，无需 curl_cffi 等指纹伪装。
2. **升级数据可从 MIT 数据集获得** —— `clashofclans.js@4.0.5` 的 `raw.json` 含 147 个单位，可生成 2073 行升级条目（troop 599 / spell 111 / hero 513 / equipment 850），字段含 `cost[]`、`time[]`、`resource`、`unlock`（`hall` / `building` / `buildingLevel`），与 `upgrade_items` 表结构对应。
3. **该数据集不含建筑数据** —— 164 个单位全为兵种、法术、英雄、装备与超级兵种，零建筑定义。`unlock.building` 仅引用建筑名称，不含等级成本。建筑升级明细因此列为范围外。
4. **原定爬虫源在大陆网络下均不可行** —— `raw.githubusercontent.com`、`cdn.jsdelivr.net` 的 gh 通道、`reddit.com`、`google.com`、`clashofclans.fandom.com` 均不可达；`clashninja.com` 可达但其 `robots.txt` 内容为 `Disallow: /`，明确禁止全站抓取。域名已备案意味着服务器位于大陆，生产环境网络画像与验证环境一致。
5. **决定** —— 爬虫移出本项目。若将来确有需要，前提是单独部署香港或海外机器，且需重新评估目标站点的 robots 策略。

**达成的影响**：一期完全不依赖爬虫，因此没有 robots 合规风险、没有 IP 封禁风险、没有跨境网络依赖。

---

## 11. 一期交付物

- 后端服务：查询、排行榜、升级数据、公告、投稿五大模块的 API
- Supercell 数据采集调度（读时旁路 + 定时批量）
- 升级数据种子导入命令
- SQLAdmin 后台（公告、升级路线、投稿审核、升级条目校正）
- Docker Compose 部署配置与 nginx 配置
- 上线到已备案域名并配置 HTTPS

## 12. 二期交付物

- 阵容与阵型页签 API
- 热门排序（`copy_count` 降序）
- 内容审核后展示流程