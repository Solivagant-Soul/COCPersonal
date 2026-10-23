# War Report 数据接入设计（赛季榜 + 阵容 + 阵型占位）

- 日期：2026-10-23
- 状态：已与人工伙伴逐段确认，待实施
- 路径：`docs/superpowers/specs/2026-10-23-warreport-data-design.md`
- 取代：`2026-10-16-cocpersonal-design.md` §3.2 中「不做阵容/阵型」与「导航只保留
  查询/排行榜」两条限制（仅限本次范围）

## 1. 背景与目标

当前站点只有「查询」与「排行榜」：排行榜是经 RoyaleAPI 代理采集的**实时全服榜**
（部落 / 玩家各 200 条，每 6 小时刷新）。官方 API 拿不到配兵、装备、赛季快照等
衍生数据。

War Report（`https://api.warreport.app`）是 COC 辅助 App 的公开 API，无需 Key，
提供：

- 赛季结束时的全服 Top 200 玩家 / 部落快照（每 28 天一份）；
- 前 200 名传奇联赛玩家的热门配兵（`GET /armies`）。

本次目标：

1. 排行榜拆成 **实时榜**（现有 RoyaleAPI 链路）与 **赛季榜**（War Report，最近 3 个
   赛季快照，下拉切换，默认最新）。
2. 新增 **阵容** 页签，展示 `GET /armies` 的热门配兵。
3. 新增 **阵型** 页签，本期只留占位。
4. 部署侧补 War Report 数据源说明，并按上游要求做**署名**。

## 2. 范围

### 2.1 做

- 新模块 `app/warreport/`（client、mapper、快照探测）。
- 新采集 job `warreport`，每日一次，落库。
- 赛季榜复用 `rankings` 表（新增两种 `kind`）。
- 新表 `warreport_armies` + 迁移 0012。
- 新路由：赛季列表、赛季榜（players/clans）、阵容。
- 前端：导航加「阵容」「阵型」；排行榜加「实时榜 / 赛季榜」；阵容页；阵型占位页；
  署名组件与全站页脚。
- 文档与配置：`WARREPORT_BASE_URL`、`docs/deployment.md`、`AGENTS.md`、`README.md`。

### 2.2 不做

- 不做 `/armies/heroes`、`/armies/equipment`、`/battle-stats`、`/clans/{tag}/videos`。
- 不做阵容历史（只保留最新一份）。
- 不做阵型内容（页面占位，接口与数据表都不动）。
- 不改现有实时榜的采集路径、缓存与契约。
- 不新增容器、端口、Python 依赖。

## 3. 上游调研结论（2026-10-23 实测）

### 3.1 基础

- OpenAPI 3.1，规范地址 `https://api.warreport.app/openapi.json`。
- 无需 API Key；`Access-Control-Allow-Origin: *`；
  `Cache-Control: public, s-maxage=3600, max-age=300`。
- 规范原文：*Attribution required: Applications using this API must credit War
  Report.* 以及 *This material is unofficial and is not endorsed by Supercell.*

### 3.2 已确认的端点与行为

| 端点 | 用途 | 关键事实 |
|---|---|---|
| `GET /locations/global/rankings/players?season=YYYY-MM-DD` | 赛季玩家榜 | 200 条；快照尚未生成时上游按 OpenAPI 返回 `[]`，日期不存在则 404 |
| `GET /locations/global/rankings/clans?season=YYYY-MM-DD` | 赛季部落榜 | 200 条 |
| `GET /locations/global/rankings/players/countries?season=...` | 探测用的小响应 | 3.8 KB，200/404 区分快照是否存在 |
| `GET /armies` | 热门配兵 | 按使用率降序；实测约 55 条 |

- **没有赛季列表接口**。`?season=` 传不存在的日期返回
  `404 {"error":"snapshot not found"}`；不带参数返回最新快照。
- 快照每 **28 天**一份。最近 4 份实测为：
  `2026-07-13`、`2026-08-10`、`2026-09-07`、`2026-10-05`。
  最近 3 个月 = 后 3 份。
- 响应里**不带快照日期**，无法从 `latest` 反推日期。

### 3.3 字段（本次用到的）

玩家：`tag`、`name`、`expLevel`、`trophies`、`attackWins`、`defenseWins`、`rank`、
`previousRank`、`clan{tag,name,badgeUrls}`、`location`。

部落：`tag`、`name`、`location`、`badgeUrls`、`clanLevel`、`members`、`clanPoints`、
`rank`、`previousRank`。

配兵：`name`、`canonicalKey`、`armyShareCode`、`armyLink`、`playerCount`、`useCount`、
`percentage`、`averageStars`、`averageDestruction`。

## 4. 总体架构

```
War Report (api.warreport.app)
        │  每日 04:23 UTC，collector job `warreport`
        ▼
app/warreport/  ── client / mappers / snapshots ──>  落库
                                                      ├─ rankings（wr_season_players / wr_season_clans）
                                                      └─ warreport_armies
        ▼
/api/v1/rankings/warreport/...  ──只读库──>  排行榜「赛季榜」
/api/v1/armies                  ──只读库──>  阵容页
```

铁律（沿用现有架构）：

- `app/warreport/` 是**唯一**与 War Report 耦合的模块，不 import FastAPI。
- `app/collector/` 不 import FastAPI。
- 路由**只读库、绝不回源**；回源只发生在采集 job。
- 单进程、`--workers 1` 不变；job 仍由同进程 APScheduler 触发。

## 5. 后端设计

### 5.1 模块与文件

```
backend/app/warreport/__init__.py
backend/app/warreport/client.py      # WarReportClient + 异常
backend/app/warreport/mappers.py     # 拍平成 rankings item / armies row
backend/app/warreport/snapshots.py   # 快照日期探测
backend/app/collector/jobs/warreport.py
backend/app/api/routes/warreport.py
```

- `WarReportClient`：`httpx.AsyncClient`，`base_url` 来自配置，超时默认 15s，无鉴权。
  只暴露 `get_json(path, params=None)`；非 2xx 抛 `WarReportError`，404 +
  `snapshot not found` 抛子类 `WarReportSnapshotNotFound`。
- mapper 只做纯数据转换，注入 `now`，不取系统时间（与官方 mapper 约定一致）。

### 5.2 配置

```python
# app/config.py
warreport_base_url: str = "https://api.warreport.app"
warreport_timeout: float = 15.0
```

- 环境变量：`WARREPORT_BASE_URL`、`WARREPORT_TIMEOUT`。
- `warreport_base_url` 允许指向测试假上游；去掉尾部 `/`。

### 5.3 数据模型

#### 5.3.1 赛季榜：复用 `rankings`

| 列 | 值 |
|---|---|
| `kind` | `wr_season_players` / `wr_season_clans` |
| `location_id` | `32000000`（scope 标记；上游本身只有 Global） |
| `league_id` | `NULL` |
| `season_id` | 快照日期 `YYYY-MM-DD` |
| `rank` / `previous_rank` | 原样 |
| `tag` / `name` | 原样（tag 归一化为 `#大写`） |
| `clan_tag` / `clan_name` / `clan_level` | 玩家行由嵌套 `clan` 拍平 |
| `points` | 部落行的 `clanPoints` |
| `trophies` / `exp_level` / `attack_wins` / `defense_wins` | 玩家行 |
| `members` | 部落行 |
| `builder_base_trophies` | `NULL` |
| `fetched_at` | 采集时间（UTC） |

- 复用 `replace_rankings(session, kind, 32000000, None, snapshot, items)`：
  自动获得「按 scope 全量替换 + 顾问锁 + 去重」。
- `RankingKind` 增加两个成员，并同步加入 `_HAS_TAG`（新 kind 都带 tag）。
- 无需迁移（表结构不变）。

#### 5.3.2 阵容：新表 `warreport_armies`（迁移 0012）

| 列 | 类型 | 约束/说明 |
|---|---|---|
| `id` | BigInteger | PK, autoincrement |
| `position` | Integer | 上游顺序，`index=True` |
| `name` | String(100) | not null |
| `canonical_key` | Text | not null, unique |
| `army_share_code` | Text | not null |
| `army_link` | Text | not null |
| `player_count` | Integer | not null |
| `use_count` | Integer | not null |
| `percentage` | Float | not null |
| `average_stars` | Float | not null |
| `average_destruction` | Float | not null |
| `fetched_at` | TIMESTAMPTZ | not null |

- 每次采集**整表替换**（`DELETE` + `INSERT`），与「榜单按 scope 全量替换」同源。
- 写入前拿一把独立事务级顾问锁 `0x57524152`（`"WRAR"`），避免调度器与手工
  `collect` 并发整表替换互相等锁。
- 不复用现有 `army_compositions`：那张表是「投稿/后台录入的阵容内容」，字段形状
  （title/description/items）与统计型配兵不同，混用会让两类数据互相污染。

### 5.4 快照日期探测

常量（`app/warreport/snapshots.py`）：

```python
SEASON_COUNT = 3                 # 只保留最近 3 份
SEASON_INTERVAL_DAYS = 28        # 上游固定 28 天一份
PROBE_TOLERANCE_DAYS = 1         # 允许提前/延后 1 天
FIRST_RUN_LOOKBACK_DAYS = 35     # 首次部署最多回溯 35 天
```

算法：

1. 从库里取已知日期：`SELECT DISTINCT season_id FROM rankings WHERE kind IN
   ('wr_season_players','wr_season_clans') ORDER BY season_id DESC`。
2. **有已知日期**：
   - 候选 = 最新已知 + 28 天；
   - 依次探测 `候选`、`候选-1`、`候选+1`（用 `players/countries?season=`）；
   - 命中 → 合并进已知集合；
   - 全不命中且 `今天 - 最新已知 >= 31 天` → 回退到首次运行的回溯探测（防止节奏漂移）；
   - 否则认为「本月还没出新快照」，结束。
3. **没有已知日期**：从「今天（UTC）」往前逐日探测，最多 35 天，命中第一个即停。
   **命中后继续补探**（R1，2026-10-23 实施期裁定）：以命中日期为锚，按
   `SEASON_INTERVAL_DAYS` 往前推，每档探 `候选`、`候选-1`、`候选+1`，直到凑满
   `SEASON_COUNT` 份或某一档三次全不命中为止。没有这一步，首次部署的赛季榜只有
   1 个选项，要等约 8 周才长到 3 个 —— 而需求就是「最近 3 个赛季」。
   回溯分支只返回补探结果，**不与 known 合并**（锚点不可信时，旧的 known 可能
   上游早已删除，继续拉只会白报失败）。
4. 取合并后日期倒序的前 3 个；只对这些日期拉全量。

- 探测只打 `players/countries`（3.8 KB），不打 231 KB 的完整榜。
- 上游 404 是**正常结果**，不计失败；网络错误/5xx 计入 `items_failed`。
- 正常情况每次运行最多 3 次探测请求；首次部署或节奏漂移回退时最多 35 次逐日探测
  加两档补探（最多 6 次），符合「共享公共服务、不要高频轮询」。

### 5.5 采集 job

`collect_warreport(client, session)`：

1. 调 `discover_snapshots()` 得到最多 3 个日期。
2. 对每个日期 × `players`/`clans`：
   - 拉完整榜 → mapper 拍平 → `replace_rankings(..., season_id=日期)`；
   - **每个 scope 单独 commit**（顾问锁随 commit 释放）。
3. 拉 `/armies` → 整表替换 `warreport_armies` → commit。
4. 返回 `{"items_ok": n, "items_failed": m, "detail": [...]}`，由 `run_job`
   汇总为 `success/partial/failed`。

调度：

```python
("23 4 * * *", "warreport", 86400)
```

- 分钟错开整点（现有为 17/13/41/29），避免与官方采集撞峰值。
- `jitter`、`max_instances=1`、`coalesce=True` 沿用现有配置。

`run_job` 的客户端选择：

- 现有 `run_job` 固定构造 `CocClient`。新增一张极小映射：

```python
if job_name == "warreport":
    client = WarReportClient(...)
else:
    client = CocClient(...)
```

- 测试显式传入 client 时照旧复用；`aclose()` 只在自建时调用。
- 不引入新的 JobContext 抽象（当前只有一个异构 job，抽象成本大于收益）。

### 5.6 API 契约

统一响应体仍是 `{"data": ..., "meta": {...}}`，`meta.cache` 大写。

#### `GET /api/v1/rankings/warreport/seasons`

```json
{
  "data": {
    "items": [
      {"seasonId": "2026-10-05", "players": 200, "clans": 200,
       "fetchedAt": "2026-10-23T04:23:11Z"}
    ]
  },
  "meta": {"cache": "HIT", "fetched_at": "...", "age_seconds": 3600, "ttl_seconds": 86400}
}
```

- 按 `season_id` 倒序；最多 3 条；`players`/`clans` 是该快照下两种 kind 的行数。
- 没有数据时 `items: []` + `cache: MISS`。

#### `GET /api/v1/rankings/warreport/seasons/{snapshot}/{kind}`

- `snapshot`：`^\d{4}-\d{2}-\d{2}$`，否则 `400 INVALID_PARAMS`。
- `kind`：`players` | `clans`，否则 `400 INVALID_PARAMS`。
- `page` 默认 1；`page_size` 默认 20，**上限 50，超限截断**。
- 返回与实时榜同形状：`items`、`total`、`kind`（`players`/`clans`）。
- 格式合法但库里没有该快照 → 200 + 空列表（与现有赛季榜行为一致）。
- `meta.ttl_seconds = 86400`（每日采集）。

#### `GET /api/v1/armies`

```json
{
  "data": {
    "items": [
      {"position": 1, "name": "Thrower", "canonicalKey": "...",
       "armyShareCode": "...", "armyLink": "https://link.clashofclans.com/?...",
       "playerCount": 54, "useCount": 332, "percentage": 27.27,
       "averageStars": 2.73, "averageDestruction": 97.25}
    ]
  },
  "meta": {"cache": "HIT", "fetched_at": "...", "age_seconds": 3600, "ttl_seconds": 86400}
}
```

- 不分页（上游约 55 条）；空表 → `items: []` + `MISS`。

### 5.7 错误处理

- 上游不可用：job 记 `failed`/`partial`，**旧数据继续可读**，页面不 500。
- 单个快照失败：其余 scope 照常提交，返回 `partial` 并列明细。
- 探测网络错误：整轮记失败（否则「快照永远不更新」会被记成 success）。
- 路由层不接触上游，因此没有 STALE 降级路径。

## 6. 前端设计

### 6.1 路由与导航

| 路径 | name | 标题 | 内容 |
|---|---|---|---|
| `/rankings` | `rankings` | 排行榜 | 实时榜 / 赛季榜 |
| `/armies` | `armies` | 阵容 | 热门配兵 |
| `/bases` | `bases` | 阵型 | 占位 |

导航顺序：`查询 / 排行榜 / 阵容 / 阵型`。

### 6.2 排行榜页

- 顶层 `el-tabs`：`实时榜`、`赛季榜`（默认实时）。
- **实时榜**：保持现有部落/玩家切换 + 卡片列表 + 分页；提示改为
  「全服 · 线上经 RoyaleAPI 代理，约每 6 小时刷新」，并显示 `meta.fetchedAt`。
- **赛季榜**：
  - 首次切到该页签时拉 `/rankings/warreport/seasons`；
  - `el-select` 选赛季，默认最新；无数据时显示「暂无赛季数据」；
  - 部落/玩家切换 + 同一个 `RankingTable` + 分页；
  - 切赛季/切类型都回到第 1 页；
  - 底部 `SourceNote`。
- `RankingTable.vue` 的 prop 从 `kind: RankingKind` 改为 `entity: 'clans' | 'players'`，
  实时榜与赛季榜共用；指标列仍是部落 `points/members/clanLevel`、玩家
  `trophies/expLevel`。

### 6.3 阵容页

- 卡片网格（窄屏单列）：配兵名、使用率 `%`、使用次数、玩家数、平均星级、
  平均摧毁率、`复制阵型` 按钮。
- 复制：`navigator.clipboard.writeText(armyLink)`；不可用/失败时 `window.open`。
  成功给 `ElMessage.success('已复制阵型链接')`。
- 顶部说明：「数据来自 War Report，统计对象为前 200 名传奇联赛玩家」。
- 空数据「暂无数据」；失败走现有 `ErrorCard`。

### 6.4 阵型页

- 标题「阵型」+ 卡片式占位文案「阵型功能开发中，敬请期待」。
- 只接通路由、导航、标题，不建数据表、不建接口。

### 6.5 署名

- `SourceNote.vue` 统一文案：
  「数据来源：War Report · 非 Supercell 官方，未获 Supercell 背书」，
  `War Report` 链到 `https://warreport.app`。
- 使用位置：赛季榜页签底部、阵容页底部。
- `MainLayout` 增加全站页脚：`本站为非官方粉丝站点 · 数据来源：Supercell 官方 API、War Report`。

### 6.6 API 封装（`frontend/src/api/endpoints.ts`）

```ts
export type RankingEntity = 'clans' | 'players'

export interface WarReportSeason {
  seasonId: string
  players: number
  clans: number
  fetchedAt: string | null
}

export interface ArmyRow {
  position: number
  name: string
  canonicalKey: string
  armyShareCode: string
  armyLink: string
  playerCount: number
  useCount: number
  percentage: number
  averageStars: number
  averageDestruction: number
}

getWarReportSeasons(): Promise<Envelope<{ items: WarReportSeason[] }>>
getWarReportSeasonRankings(
  snapshot: string, entity: RankingEntity, page = 1, pageSize = 20,
): Promise<Envelope<RankingsPage>>
getArmies(): Promise<Envelope<{ items: ArmyRow[] }>>
```

- URL 与查询参数名只出现在此文件；`page_size` 仍是蛇形。
- `getRankings` 的 `kind` 改为 `RankingEntity`（值域不变，纯类型收敛）。

## 7. 署名与合规

上游要求（原文）：

> Attribution required: Applications using this API must credit War Report.
>
> *This material is unofficial and is not endorsed by Supercell.*

落点：

1. 赛季榜页签、阵容页：`SourceNote` 可见链接。
2. 全站页脚：数据来源一行。
3. `docs/deployment.md`：专节说明署名义务与原文。
4. `README.md`：功能清单与数据来源。
5. 根 `AGENTS.md`：加一条「War Report 署名是使用条件」。

不把署名藏进注释或仅放在文档里 —— 页面可见才算满足「credit」。

## 8. 部署变更

- 无新容器、无新端口、无新 Python 依赖（`httpx` 已有）。
- 出网要求：服务器可访问 `https://api.warreport.app`（无需 Key、无需 IP 白名单）。
- 迁移：`alembic upgrade head` 建 `warreport_armies`（容器启动流程已包含）。
- 首次数据：`python -m app.cli collect warreport`，或等每日 `04:23 UTC`。
- `.env`：

```dotenv
# War Report（赛季榜 / 阵容）。无需 Key；上游要求署名，见部署文档 §12。
WARREPORT_BASE_URL=https://api.warreport.app
WARREPORT_TIMEOUT=15
```

- **`docker-compose.yml` 的 `api.environment` 是显式白名单**（不是 `env_file`
  整体透传），必须补两行，否则 `.env` 里的值进不了容器：

```yaml
WARREPORT_BASE_URL: ${WARREPORT_BASE_URL:-https://api.warreport.app}
WARREPORT_TIMEOUT: ${WARREPORT_TIMEOUT:-15}
```

- `backend/.env.example` 与根 `.env.example` 同步；`tests/test_deployment_config.py`
  若断言变量清单，需要同步更新。

- `docs/deployment.md` 新增 §12「War Report 数据源与署名」，原 §12「已知问题」
  顺延为 §13。内容：
  - 用途与端点；
  - 无 Key/白名单、每日一次、不要高频轮询；
  - 署名原文与本站落点；
  - 非 Supercell 官方 / Fan Content Policy 口径；
  - 快照探测机制；404 `snapshot not found` 是正常结果；
  - 验证命令：`curl /armies`、`collect warreport`、查赛季列表接口；
  - 上游不可用时的表现（旧数据 + `collector_runs` 记账，不 500）。

## 9. 测试策略

### 9.1 后端

- `tests/warreport/test_client.py`：200、404（快照不存在）、5xx/网络错误映射；
  base_url 去尾斜杠。
- `tests/warreport/test_mappers.py`：玩家嵌套 `clan` 拍平、部落 `clanPoints→points`、
  tag 归一化、配兵字段与 `position`。
- `tests/warreport/test_snapshots.py`：
  - 无已知日期 → 回溯探测命中最新的；
  - 有已知日期 + 新快照存在 → 只探 3 个候选；
  - 有已知日期 + 无新快照 → 不发多余请求、返回已知前 3；
  - 超过 31 天未更新 → 回退回溯。
- `tests/collector/test_warreport_job.py`：假 client + 真 session；断言两种 kind 按
  scope 全量替换、阵容整表替换、单个快照失败仍提交其余并返回 `partial`。
- `tests/api/test_rankings_warreport.py`：赛季列表倒序与计数、分页、
  `page_size=100` 截断为 50、非法 snapshot/kind 返回 400、空数据 200。
- `tests/api/test_armies.py`：返回形状、顺序、`meta`、空表。
- `tests/db/test_warreport_models.py`：迁移后表存在、`canonical_key` 唯一。
- 全量 `python -m pytest -q` 必须全绿。

### 9.2 前端

- `Rankings.spec.ts`：两个页签；赛季榜默认最新；切赛季/切类型重新拉取；
  署名可见；实时榜仍按 `('clans', 32000000, 1, 20)` 调用。
- `Armies.spec.ts`：渲染配兵、复制按钮调用 clipboard、空态、署名。
- `router/index.spec.ts`：`/armies`、`/bases` 路由与标题；导航四项。
- `npm run test`、`npm run build` 必须全绿。

### 9.3 手工验收（本机可做）

1. 起 PG（`C:\pgportable`）+ 后端 + Vite。
2. `python -m app.cli collect warreport`（真实上游，可联网）。
3. `/rankings` 切到赛季榜：3 个日期、部落/玩家各 200 条。
4. `/armies`：约 55 条配兵，复制按钮可用。
5. `/bases`：占位文案。
6. 断网重跑 `collect`：命令非 0，`collector_runs` 记 `failed`，页面仍显示旧数据。

## 10. 验收标准

1. 无 War Report 网络时，赛季榜/阵容页仍能打开：有旧数据则显示，无数据则空态，
   **不出现 500**。
2. 首次 `collect warreport` 后，赛季下拉出现 3 个日期，每种榜 200 条；阵容非空
   （条数随上游快照变化，2026-10-23 实测 13 条，不要写死）。
3. 赛季榜与阵容页均可见 War Report 署名链接；全站页脚可见数据来源。
4. `docs/deployment.md` 可照着从零跑通一次采集，并说明署名义务。
5. 后端全量测试、前端测试与构建全绿。

## 11. 裁定记录

| 编号 | 裁定 | 理由 |
|---|---|---|
| WR1 | 赛季榜复用 `rankings`，新增 `wr_season_players` / `wr_season_clans` | 刷新、分页、契约全部现成；新表会复制一遍相同逻辑 |
| WR2 | 阵容新建 `warreport_armies`，不复用 `army_compositions` | 后者是投稿/后台内容，形状不同，混用会污染两类数据 |
| WR3 | 快照日期靠探测，不落「赛季元数据表」 | 上游无列表接口；3 个日期可从 `rankings` 的 `DISTINCT` 得到 |
| WR4 | 阵容只留最新一份，不做历史 | 需求只要「当前热门配兵」；历史会显著放大存储与 UI 复杂度 |
| WR5 | `run_job` 内按 job 名选择客户端，不引入 JobContext | 当前只有一个异构 job，最小改动 |
| WR6 | 署名放页面可见处 + 全站页脚 + 部署文档 | 上游要求 credit；只在文档里写不算 |
| WR7 | 阵型页只做占位 | 需求明确「留空，后续开发」 |
| WR8 | 首次运行命中最新快照后**继续按 28 天补探**，一次凑满 3 个赛季（实施期裁定，2026-10-23） | 原「命中第一个即停」会让新部署的赛季榜只有 1 个选项，要等约 8 周才长到 3 个，与「最近 3 个赛季」的需求直接冲突；代价是首跑多 6 次 3.8 KB 的小请求 |

## 12. 风险与后续

- **快照节奏漂移**：上游文档写 28 天，但若漂移到 ±2 天以上，锚点探测会漏。
  已有「超过 31 天回退逐日探测」兜底。
- **上游变更**：War Report 是第三方个人服务，字段可能变。mapper 对缺失字段留空、
  不让整批失败；`collector_runs.error` 保留明细。
- **署名**：若上游未来要求更具体的文案或 logo，需要改 `SourceNote.vue` 一处。
- **阵型**：本期不建表；后续接入时再单独出规格（图片存储、复制链接、审核流程）。
