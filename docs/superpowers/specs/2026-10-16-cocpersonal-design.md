# COCPersonal 设计规格（前后端一体）

- 日期：2026-10-16
- 状态：待人工评审
- 路径：`docs/superpowers/specs/2026-10-16-cocpersonal-design.md`

## 1. 背景与目标

在同级 `COCBack`（FastAPI + SQLAlchemy async + PostgreSQL 的 COC 后端）与 `COC`（微信小程序前端）
之外，新建 **`COCPersonal`**：一个把**网页前端与后端放在同一仓库**的个人项目。

- **目的**：把 COC 助手做成**浏览器访问的网页应用**（PC 端为主），供个人使用。
- **开发机**：Windows 做主力，负责开发、提交、浏览器访问。
- **部署**：后期在**另一台 Linux 机器**上用 Docker Compose 部署。
- **MVP 功能**：查询（玩家 / 部落）+ 排行榜。
- **导航**：网页只保留「查询」「排行榜」两项；投稿 / 公告 / 后台**不进网页导航**。

## 2. 现状（调研结论）

| 目录 | 角色 | 远程 |
|------|------|------|
| `COC` | 微信小程序前端（WXML，跑在微信开发者工具，非浏览器） | `.../COC.git` |
| `COCBack` | FastAPI 后端：官方 API 对接、读时旁路缓存、定时采集、限流、sqladmin 后台、投稿/公告、9 个 alembic 迁移、486 个测试 | `.../COCBack.git` |
| `COCBack_personal` | `COCBack` 的个人克隆 | `.../COCBack.git` |
| `COCPersonal` | **本项目**（空仓，已 `git init` + 关联远程） | `.../COCPersonal.git` |

小程序那套 WXML/`wx.request` **不能**直接跑浏览器，前端必须重写；但它的 **API 契约**（见 §10）可直接沿用。

## 3. 范围

### 3.1 做（MVP）
- 后端从 `COCBack` **全量搬入** `backend/`，保持现有结构与行为。
- 新增**开发夹具**：占位 token 下让查询/排行页面能看到真实形状的数据。
- 新建网页前端：查询（玩家 / 部落）+ 排行榜。
- 本地联调跑通（Windows：PostgreSQL + 后端 + Vite 开发服务器 + 浏览器）。
- 组合部署资产（Docker Compose：nginx + api + postgres），Linux 可部署。

### 3.2 不做（非目标 / 后续）
- 不做「我的 / 升级数据 / 升级路线 / 投稿 / 公告」等页面的网页版。
- 不做账号体系（`users` / `user_clan_subscriptions` 仍是后端地基，前端不接）。
- 不接真实 `COC_API_TOKEN`（先用夹具）。
- 不做 HTTPS 证书签发（留成可开关，见 §9）。
- 不重写 / 裁剪后端已有功能代码（全量保留）。
- 不做爬虫（沿用 COCBack 的约定：爬虫另立项目）。

## 4. 总体架构

前后端分离、同仓两目录，浏览器访问由 nginx 统一入口：

```
浏览器(PC)  ──HTTP──>  nginx(web)
                        ├── /            前端静态 SPA (Vue dist)
                        ├── /api/        ──> api (FastAPI, :8000)
                        ├── /media/      ──> api 媒体卷(只读)
                        ├── /admin/      ──> api (sqladmin，非导航入口)
                        └── /healthz /readyz ──> api 探针
                                              └── postgres:16
```

- 开发期无需 nginx：Vite dev server 起在 `:5173`，`/api` 代理到本机 `:8000`。
- 单副本一体：`api` 容器 `--workers 1`，API 与采集调度器同进程（沿用 COCBack 硬约束）。

## 5. 仓库结构

```
COCPersonal/
├── backend/                     # 从 COCBack 全量搬入
│   ├── app/                     # api/ cache/ coc/ collector/ content/ db/ cli.py config.py main.py ...
│   ├── migrations/              # alembic（0001..0009）
│   ├── tests/                   # 486 个测试 + fixtures/
│   ├── pyproject.toml  alembic.ini  Dockerfile
│   ├── .env.example  README.md  # README 为 Dockerfile COPY 所需（COCBack 缺失，须补）
│   └── deploy/                  # 保留原 nginx.conf 作为参考/部署侧资产
├── frontend/                    # 新建 Vue3 应用
│   ├── src/{api,pages,components,router,stores,utils}/
│   ├── index.html  package.json  vite.config.ts  tsconfig.json
│   └── Dockerfile               # 多阶段：node 构建 → nginx 托管
├── deploy/
│   └── nginx.conf               # HTTP-only 默认；HTTPS 段作为可开关参考
├── docker-compose.yml           # postgres + api + web（仅 web 对外）
├── .env.example                 # 组合栈的环境变量占位
├── .gitignore
├── README.md                    # 开发 / 构建 / 部署说明
└── AGENTS.md                    # 更新为「本项目」的使用说明
```

## 6. 后端（搬入与改动）

**搬入**：整目录复制 `COCBack/{app,migrations,tests,pyproject.toml,alembic.ini,Dockerfile,.env.example}` 到
`backend/`。保留全部：COC 客户端 / 令牌桶 / 缓存、采集器（APScheduler）、8 组路由、sqladmin 后台、
投稿/公告、9 个迁移、486 个测试。

**必须的改动（很小）**：
1. 新建 `backend/README.md`——`Dockerfile` 有 `COPY pyproject.toml README.md ./`，而 COCBack 根**没有**
   README.md（本机 Docker 从未跑过，见 R12），不补则镜像构建失败。
2. 新增 **dev 夹具上游**（见 §8）：`COC_API_TOKEN` 为空/占位时不打官方 API，改由本地夹具数据应答。
3. 新增 **`python -m app.cli seed-dev-rankings`**：把 `tests/fixtures/` 的排行样本灌入 PG。

**保持不变的硬约束**（沿用 COCBack AGENTS.md，搬入后同样有效）：
- 单进程一体，`CMD ... --workers 1` 不可改（令牌桶/调度器/缓存均为进程内）。
- `sqlalchemy>=2.0,<2.1` 不得放宽（2.1.x 的 C 扩展在本机与 Docker 客户机均加载失败）。
- `migrations/env.py` 必须 import 模型、必须走异步引擎；`alembic.ini` 必须纯 ASCII。
- 判 `alembic upgrade head` 前先 `alembic stamp head`（空库）。
- 测试环境变量必须在任何 `app.*` import 之前设置（`tests/conftest.py` 已处理）。
- 模块级 `engine` 每用例后 `dispose()`；`client` fixture 是异步的，禁用同步 `TestClient`。

## 7. 前端

**技术栈**：Vue 3 + Vite + TypeScript + Vue Router + Pinia + **Element Plus（PC 桌面端）** + axios。

**目录（拟）**：
```
frontend/src/
├── api/          request.ts（统一信封/错误码）+ endpoints.ts（typed 调用）
├── pages/        QueryHome.vue  PlayerDetail.vue  ClanDetail.vue  Rankings.vue
├── components/   ErrorCard.vue  LoadingBlock.vue  TagInput.vue
├── router/       index.ts
├── stores/       （需要时）query.ts
└── utils/        format.ts（移植 COC/utils/format.js 的格式化，含大数防护）
```

**路由与 MVP 页面**（左侧导航仅两项）：
| 路由 | 页面 | 后端接口 |
|------|------|----------|
| `/` | 查询首页（输入玩家 tag） | — |
| `/players/:tag` | 玩家详情 | `GET /api/v1/players/{tag}` |
| `/clans/:tag` | 部落详情 | `GET /api/v1/clans/{tag}` |
| `/rankings` | 排行榜（**全服**，部落 / 玩家两类） | `GET /api/v1/locations` + `GET /api/v1/rankings/{clans\|players}` |

**API 客户端**（`src/api/request.ts`，移植小程序 `COC/utils/request.js` 的**契约**，用 axios 重写）：
- 统一信封：成功 `{data, meta:{cache, fetched_at, age_seconds, ttl_seconds}}`；`meta` 蛇形→驼峰。
- 错误体：`{error:{code, message, upstream_reason}}`，**透传后端 code，不重映射**。
- 前端自有码：`BAD_RESPONSE`（信封损坏）、`NETWORK_ERROR`（网络失败）。
- `meta.cache === 'STALE'` **不是错误**，HTTP 200 照常渲染（页面可提示"数据可能过期"）。
- `BASE_URL` 走环境变量 `VITE_API_BASE`；开发留空走 Vite 代理，生产用同域 `/api`。

## 8. 开发夹具与本地数据（占位 token）

目标：**没有真实 `COC_API_TOKEN` 也能把界面跑通**，同时仍走真实后端契约。

1. **dev 夹具上游**：当 `COC_API_TOKEN` 为空或等于占位值（如 `PLACEHOLDER`）时，`CocClient` 改为从
   `backend/tests/fixtures/`（`player_profile.json` / `clan_detail.json` / `clans` 搜索样本等）返回。
   - 实现位置限定在 `app/coc/`（COCBack 约定：唯一允许耦合上游的模块）。
   - 夹具响应必须与真实响应同形状，且带 `_source`/`_todo` 标记，避免被误当真数据。
2. **排行榜种子**：`python -m app.cli seed-dev-rankings` 读 `tests/fixtures/ranking_clans.json`，
   经既有 upsert 路径写入 `rankings` 表，使 `/api/v1/rankings/*` 有数据可读。
3. **备选**：前端可用 MSW 假数据**不启后端**独立开发 UI；仅作备用，不作为主路径（验证不到后端契约）。

## 9. 部署（Linux，Docker Compose）

根 `docker-compose.yml` 三服务，**只有 `web` 映射 80/443**：
- `postgres`：`postgres:16-alpine`，命名卷 `pgdata`，healthcheck `pg_isready`。
- `api`：`build: ./backend`，`APP_ROLE=all`，`DATABASE_URL` 指向 `postgres`，`--workers 1`（镜像内已固定）。
- `web`：`build: ./frontend`（多阶段：node 构建 `dist` → `nginx:1.27-alpine`），挂载 `deploy/nginx.conf`。

**nginx 关键差异（相对 COCBack）**：
- `location /` 改为 **SPA 静态托管 + `try_files $uri /index.html`**（COCBack 原是 `return 404`）。
- **默认 HTTP-only**：不加 `ssl` 段、不做 HTTP→HTTPS 强制跳转。
- 保留反代：`/api/`、`/media/`（alias + `autoindex off`）、`/admin/`、`/healthz`、`/readyz`。
- 保留 `X-Forwarded-For` 透传（否则全网共用一个限流桶）。

**HTTPS 开关（预留，现在不做）**：nginx.conf 内保留注释版 `443 ssl` server 段与 certbot 目录挂载点；
拿到域名后启用并挂 `deploy/certs/`，配合 certbot 续期脚本即可，前端/后端代码不动。

**生产 `.env` 必填**：`POSTGRES_PASSWORD`、`COC_API_TOKEN`（将来）、`ADMIN_USERNAME`、`ADMIN_PASSWORD`、
`ADMIN_SECRET_KEY`（随机）、`PUBLIC_BASE_URL`。

## 10. 接口契约摘要（前端依赖，源自 COCBack 规格 §6）

- 成功体：`{"data": ..., "meta": {"cache", "fetched_at", "age_seconds", "ttl_seconds"}}`。
- **`meta.cache` 大写**：`HIT` / `MISS` / `STALE`。
- 分页：`page` 默认 1，`page_size` 默认 20，**上限 50 且超限截断为 50**（返回 200，不是 422）。
- 错误体：`{"error": {"code", "message", "upstream_reason"}}`；错误码如 `INVALID_TAG`、`INVALID_PARAMS`、
  `CLAN_NOT_FOUND`、`PLAYER_NOT_FOUND`、`UPSTREAM_THROLED`、`UPSTREAM_UNAVAILABLE`、`COC_UNKNOWN`。
- 限流：对外 60 次/分钟/IP；`/healthz`、`/readyz` 豁免。
- `meta.cache === STALE`：回源失败但有旧数据，仍 HTTP 200。

## 11. 测试与验证

- **后端**：`cd backend; python -m pytest -q`——搬入后必须保持全绿；新增夹具与 seed 需带测试
  （能在错误实现上失败的测试才算数）。
- **前端**：`npm run build` 必须通过；Vitest 覆盖 `api/request.ts`（信封解包、meta 驼峰、错误码透传、
  STALE 不特判）与 `utils/format.ts`。
- **端到端手测**：本机起 PG（`C:\pgportable`，`:5433`）+ 后端 + Vite，浏览器 `http://localhost:5173`
  过一遍 4 个 MVP 页面（含空态与错误卡片）。

## 12. 本地开发环境（Windows）

- **数据库**：沿用本机免安装 PostgreSQL（`C:\pgportable`，监听 `127.0.0.1:5433`，trust）。
  本机 CPU 虚拟化在固件层关闭（R12），**Docker Desktop / WSL2 不可用**。
- **后端**：`cd backend` → 复制 `.env.example` 为 `.env` 填值 → `python -m uvicorn app.main:app --reload --port 8000`。
  未建 `.env` 时 alembic / app.cli 会因缺必填项直接失败。
- **前端**：`cd frontend` → `npm install` → `npm run dev`（`:5173`，`/api` 代理到 `:8000`）。
- **浏览器**：`http://localhost:5173`。
- **Windows bash 陷阱**：本机唯一可用 bash 是 `D:\Program Files\Git\bin\bash.exe`（PATH 上的 `bash` 是
  未安装 WSL 的转发桩）。superpowers 技能脚本须用上述 Git Bash 解释器执行。

## 13. 决策记录

| 编号 | 决策 | 理由 |
|------|------|------|
| R1 | 前端重写为网页（Vue3），不沿用小程序 | 小程序不在浏览器运行，且目标为"浏览器访问" |
| R2 | 前端用 Element Plus（PC 桌面端） | 用户明确 PC 浏览器使用 |
| R3 | 后端全量搬入 `backend/` | 后续扩展零返工，且带 486 个已验证测试 |
| R4 | MVP 只做查询 + 排行榜 | 先跑通主链路 |
| R5 | 网页导航只留查询 + 排行榜 | 用户要求剥离投稿/公告/后台入口（后端保留） |
| R6 | 先 HTTP，HTTPS 留开关 | 无域名/无公网前置；个人项目先跑通 |
| R7 | 用 dev 夹具上游 + 排行种子 | 无真实 token 也能跑通界面并验证契约 |
| R8 | 前后端同仓两顶级目录 | "前后端在一起"，开发/部署都清晰 |
| R9 | 部署 = Docker Compose(web+api+postgres) | 沿用 COCBack 形态，Linux 单机可部署 |

## 14. 风险与未决

- **Docker 本机不可用**（R12 虚拟化关闭）：`docker compose up` 的端到端验证**只能在 Linux 机器上做**，
  本机最多验证到镜像构建产物与配置正确性。
- **夹具数据是手搓占位**：`tests/fixtures/` 四份样本带 `_source`/`_todo` 自报身份；将来拿到真实 token
  要换成真实响应。
- **Element Plus 体积/桌面假设**：若日后要兼顾手机浏览器，需补响应式，当前只按 PC 设计。
- **排行榜依赖采集写库**：种子脚本只造夹具数据；真实排名仍需 token + 采集器。

## 15. 交付里程碑（供 writing-plans 拆任务）

1. 骨架：`backend/` 全量搬入 + 补 `README.md` + 根 `.gitignore` + 更新 `AGENTS.md`。
2. 后端 dev 夹具（stub 上游 + `seed-dev-rankings`）+ 测试。
3. 前端脚手架（Vite + Vue3 + TS + Element Plus + Router + Pinia）。
4. 前端 API 客户端 + 契约单测。
5. MVP 页面（查询首页 / 玩家详情 / 部落详情 / 排行榜）。
6. 本地联调跑通（PG + 后端 + Vite + 浏览器手测）。
7. 部署资产（`frontend/Dockerfile`、`deploy/nginx.conf`、根 `docker-compose.yml`、`.env.example`）。
8. 文档（根 `README.md` 的开发 / 构建 / 部署说明）。

> **裁定（2026-10-22）**：排行榜收窄为「**全服（Global, 32000000）的部落榜与
> 玩家榜**」。都城榜 / 部落基地榜 / 玩家基地榜不再采集，路由返回 404，
> `/locations` 只返回全服（前端不再需要挑地区）。迁移 0011 清掉库里的历史行。
> 赛季榜（`season_players`）**不受影响** —— 它是另一条 scope
> （`league_id` + `season_id`，无 `location_id`）。
