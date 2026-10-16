# COC 后端 使用说明

> 本地开发与部署的操作手册。**部署上线请看 [`deployment.md`](./deployment.md)**，
> 那份是八步上线清单，本文是日常怎么用。

---

## 这是什么

给微信小程序做的 COC（部落冲突）数据后端。

- 从 Supercell 官方 API 定时采集部落、玩家、战报、排行榜数据
  （默认直连官方；也可走 RoyaleAPI 代理免自建 IP 白名单，见 `AGENTS.md`「上游接入」）
- 升级数据来自 MIT 许可的开源数据集（`clashofclans.js`），**不消耗 Supercell 配额**
- 提供查询接口给小程序调用，另有一个单管理员后台

**技术栈**：FastAPI + SQLAlchemy 2.0 async + PostgreSQL 16 + APScheduler + SQLAdmin

---

## 快速开始（本地）

### 前置

| 项 | 说明 |
| --- | --- |
| Python | 3.12（本机无需 venv，`python -m pytest` 直接可用） |
| PostgreSQL | 任意 16.x 实例。本机用 `C:\pgportable` 免安装版，监听 `127.0.0.1:5433` |
| 环境变量 | 见下方"配置" |

### 1. 配置

```bash
cp .env.example .env
```

`.env` 至少要填这三项，其余留默认：

```bash
DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:5433/postgres
PUBLIC_BASE_URL=http://localhost:8000
COC_API_TOKEN=          # 留空也能跑测试，只是真实请求会被 401
COC_BASE_URL=           # 留空走官方；填 https://cocproxy.royaleapi.dev/v1 走 RoyaleAPI 代理
```

`ADMIN_USERNAME` / `ADMIN_PASSWORD` / `ADMIN_SECRET_KEY` 只有登录后台才需要。

### 2. 建表

```bash
alembic upgrade head
```

> 迁移链 `0001`–`0009`，共 27 张表。

### 3. 跑测试

```bash
python -m pytest -q                    # 全量，约 65 秒
python -m pytest tests/api -q          # 单目录
python -m pytest tests/api/test_clans.py::test_get_clan_returns_200 -q   # 单用例
```

测试连的是**同一个** `.env` 里的库，每个用例前后自动截断所有表 —— 不要手工
往里塞数据，别的用例看不到。

### 4. 导入升级数据（一次性）

```bash
python -m app.cli import-game-data --dry-run    # 先看统计，不写库
python -m app.cli import-game-data             # 实际写入
```

产出 **2073 行**（troop 599 / spell 111 / hero 513 / equipment 850）。
可重复执行，不会重复插入。

加 `--cache-dir .cache/npm` 后 tarball 会落盘，之后可离线重跑。

### 5. 启动服务

```bash
uvicorn app.main:app --reload --port 8000
```

- 接口文档：http://localhost:8000/docs
- 后台：http://localhost:8000/admin/ （需 `ADMIN_USERNAME` / `ADMIN_PASSWORD`）

> **`--workers` 只能是 1。** 多 worker = 多个令牌桶 + 多个调度器，对 Supercell
> 的实际请求速率会翻倍并被限流。详见 `AGENTS.md` 的「架构边界」。

---

## 接口一览

所有响应统一为：

```json
{
  "data": { "...": "..." },
  "meta": {
    "cache": "HIT",
    "fetched_at": "2026-10-10T08:00:00Z",
    "age_seconds": 120,
    "ttl_seconds": 300
  }
}
```

**`meta.cache` 的值是大写的** `HIT` / `MISS` / `STALE` —— 小写会直接破坏前端契约。
`ttl_seconds == 0` 表示这是内容数据（升级/公告/投稿），没有回源也没有过期。

错误统一为：

```json
{ "error": { "code": "CLAN_NOT_FOUND", "message": "...", "upstream_reason": "notFound" } }
```

### 官方数据（会消耗 Supercell 配额，按需回源）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/clans/search?query=&limit=` | 部落搜索 |
| GET | `/api/v1/clans/{tag}` | 部落详情 |
| GET | `/api/v1/clans/{tag}/members` | 成员列表 |
| GET | `/api/v1/clans/{tag}/warlog` | 战报 |
| GET | `/api/v1/clans/{tag}/currentwar` | 当前战 |
| GET | `/api/v1/clans/{tag}/cwl` | CWL 联赛组 |
| GET | `/api/v1/players/{tag}` | 玩家详情 |
| POST | `/api/v1/players/{tag}/verifytoken` | 校验玩家 API token |

### 排行榜（**只读库，不回源** —— 由定时任务写入）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/rankings/clans` | 部落榜，`locationId` 默认 32000001（中国） |
| GET | `/api/v1/rankings/players` | 玩家榜 |
| GET | `/api/v1/rankings/capitals` | 都城榜 |
| GET | `/api/v1/rankings/clans_builder_base` | 部落基地榜 |
| GET | `/api/v1/rankings/players_builder_base` | 玩家基地榜 |
| GET | `/api/v1/rankings/season/{league_id}/{season_id}` | 赛季榜 |
| GET | `/api/v1/locations` | 地区列表 |
| GET | `/api/v1/leagues/{kind}` | 联赛，`kind` = war/capital/builder_base |
| GET | `/api/v1/seasons/{league_id}` | 赛季列表 |
| GET | `/api/v1/meta/freshness` | 各榜单最后采集时间 + 采集成败 |

### 内容数据

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/upgrade/items?category=&village=&name=` | 升级条目 |
| GET | `/api/v1/upgrade/routes?from_th=&to_th=` | 升级路线 |
| GET | `/api/v1/upgrade/routes/{id}` | 路线详情（含步骤） |
| GET | `/api/v1/announcements?category=` | 公告 |
| GET | `/api/v1/announcements/{id}` | 公告详情 |
| POST | `/api/v1/submissions` | 投稿 |
| GET | `/api/v1/submissions/{id}` | 投稿状态 |

### 运维

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/healthz` | 存活探针，不查任何依赖 |
| GET | `/readyz` | 就绪探针，查 DB 与调度器 |
| — | `/admin/` | SQLAdmin 后台 |

### 分页

所有列表接口统一：`page`（默认 1）、`page_size`（默认 20，**上限 50**）。

`?page_size=500` 会返回 **200 + 截断到 50**，不是 422 —— 这是刻意的，
前端不用处理两种响应形状。`page` 越界返回空列表，不是 404。

### 限流

每 IP 每分钟 60 次（`RATE_LIMIT_PER_MINUTE`）。超了返回 429 + `Retry-After` 头。

**`/healthz` 与 `/readyz` 不计入** —— 容器探针要能无限调用，否则服务会被自己的
健康检查打死。nginx 必须透传 `X-Forwarded-For`，否则全网共用一个桶。

---

## 后台怎么用

`https://你的域名/admin/`，用 `.env` 里的账号密码登录。

| 页面 | 能做什么 |
| --- | --- |
| 公告 | 录入、编辑、发布、置顶 |
| 投稿 | 只读列表 + 「通过」「驳回」两个动作 |
| 升级条目 | **唯一可编辑的官方派生数据** —— 用来补 `name_zh` 与 `builder_count` |
| 升级路线 | 录入路线与步骤 |
| 阵容 / 阵型 | 只读（内容来自投稿审核） |
| 部落 / 玩家 / 排行榜 / 采集记录 | **全部只读** |

采集表（地区、联赛、赛季、成员、战报等）**没有注册到后台**，避免误删导致
采集静默失效。

**改完密码无需重启** —— 每个请求都会重新比对环境变量，旧会话自动失效。
但 `ADMIN_SECRET_KEY` 改了需要重启。

---

## 定时采集

同进程跑（`APP_ROLE=all` 时），调度器在应用生命周期内启动。

| job | 频率 | 内容 |
| --- | --- | --- |
| `static_data` | 每天 03:17 | 地区、联赛层级、标签 |
| `rankings` | 每 6 小时（:13/:19/...） | 5 类地区榜 |
| `leagues` | 每小时 :41 | 三类联赛 |
| `seasons` | 每小时 :29 | 赛季清单 + **仅当前赛季**的排名 |

cron 刻意错开整点 —— 官方在整点压力最大。

**查采集状态**：

```bash
curl -s localhost:8000/api/v1/meta/freshness | python3 -m json.tool
```

`collectorRuns` 里 `status` 为 `partial` 表示部分失败，`failed` 表示全挂，
`detail` 里有具体是哪个地区。

---

## 排错

| 现象 | 先查什么 |
| --- | --- |
| 接口返回 `null` 而不是对象 | 路由没返回 `DataOut`，或 `response_model` 用错了 |
| `meta.cache` 是小写 | 有地方绕过了 `readthrough.CacheStatus`，直接写字符串 |
| `?page_size=500` 返回 422 | 有地方用了 `Field(le=50)` 而不是 `clamp_page_size` |
| 时间差 8 小时 | 时间列少了 `DateTime(timezone=True)`（naive datetime） |
| tag 找不到 | 绕过 `app.coc.tags.normalize_tag` 自行 `strip().upper()` 了 |
| 测试单独过、连着跑炸 | 用了同步 `TestClient`；必须用异步 `httpx.AsyncClient` |
| `Event loop is closed` | 有模块级连接池跨事件循环存活 |
| 榜单一直是空 | 采集还没跑到该 scope，查 `/api/v1/meta/freshness` |
| 后台登录后立刻掉线 | `ADMIN_SECRET_KEY` 没设或改了没重启 |
| 429 来得莫名其妙 | nginx 没透传 `X-Forwarded-For`，全网共用一个桶 |
| 403 `accessDenied.invalidIp` | 走 RoyaleAPI 代理时，key 的 Allowed IP 必须填**代理的 `45.79.218.79`**，不是你服务器的 IP；`COC_BASE_URL` 是否指向 `https://cocproxy.royaleapi.dev/v1` |

更完整的环境陷阱清单见仓库根目录的 `AGENTS.md`。

---

## 常用命令

```bash
# 数据库迁移
alembic upgrade head                      # 应用迁移
alembic current                           # 当前版本
alembic revision --autogenerate -m "xxx"  # 生成迁移（见 AGENTS.md 的坑）

# 导入升级数据
python -m app.cli import-game-data --dry-run
python -m app.cli import-game-data --cache-dir .cache/npm

# 测试
python -m pytest -q --no-header -p no:cacheprovider    # 输出更干净
python -m pytest -k "warlog" -q                        # 按名字筛

# 本机 PostgreSQL（R12：虚拟化被关，Docker/WSL 不可用）
C:\pgportable\pgsql\bin\pg_isready.exe -h 127.0.0.1 -p 5433 -U postgres
```

---

## 代码地图

```
app/
  main.py              应用工厂：路由挂载、中间件、lifespan（启动调度器）
  config.py            环境变量
  middleware.py        对外 IP 限流
  api/
    schemas.py         统一响应体 + clamp_page_size（全项目唯一分页截断点）
    errors.py          CocError → HTTP 状态码映射
    deps.py            CocClient 依赖
    routes/            clans / players / rankings / upgrade / content / submissions / admin
  coc/                 唯一与 Supercell 耦合的模块
    client.py          httpx + 令牌桶 + 指数退避
    ratelimit.py       RateLimiter 接口 + MemoryRateLimiter
    endpoints.py       30 个官方接口封装
    errors.py          CocError 层次（业务态 / 故障态 / 访问拒绝）
    tags.py            tag 归一化与 URL 转义
    mappers.py         官方响应 → ORM
  cache/
    readthrough.py     读时旁路（HIT/MISS/STALE 与降级规则）
    ttl.py             各资源 TTL
  collector/           定时采集（**不 import FastAPI**）
    scheduler.py       APScheduler 装配 + APP_ROLE 门控
    service.py         job 编排与运行记录
    jobs/              static_data / rankings / leagues / seasons
  content/             内容业务（**不 import FastAPI**）
    game_data.py       npm 数据集 → upgrade_items
    submissions.py     投稿审核流转
  db/
    models.py          27 张表的 ORM
    session.py         异步 session
migrations/versions/   0001–0009
tests/                 479 个用例
```

**架构边界**：`app/coc/` 是唯一允许与 Supercell 耦合的模块；
`app/collector/` 与 `app/content/` 都不得 import FastAPI 或 `app.api`
（`APP_ROLE=collector` 时要能脱离 HTTP 层单独起进程）。这两条都有测试用 AST 静态锁定。