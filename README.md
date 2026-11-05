# COCPersonal

《部落冲突》（Clash of Clans）资料查询站 —— 浏览器访问的网页应用。

前端是同仓的 Vue 3 单页应用，后端是 FastAPI 服务（整体搬自 COCBack），
数据落在 PostgreSQL，单机 Docker Compose 部署。项目以 PC 浏览器为主，
个人使用，不含账号体系；小程序版不在本仓库内。

## 功能

| 模块 | 说明 |
| --- | --- |
| **查询** | 按标签查询玩家 / 部落档案。玩家页含战报，部落页含成员列表 |
| **排行榜** | 全服部落榜与玩家榜（部落 / 玩家切换、分页），显示榜单抓取时间；读时缓存 + 定时采集 |
| **赛季榜** | 最近 3 个赛季快照切换，展示职业选手与头部玩家的赛季数据 |
| **阵容** | 解析分享码，展示热门配兵、兵种等级与图标 |
| **阵型** | 18 本防守阵图集：卡片浏览、等级筛选、复制官方链接；站长可在页面内上传，上传即发布 |
| **体验** | 深色主题、搜索历史、收藏、统一加载态与错误页、友好 404 |

后端还保留着部落搜索、战争日志、当前战争、CWL、升级数据、公告、投稿等接口，
供后续页面或外部调用使用；网页导航只呈现上面五项。

## 架构

前后端分离、同仓两目录，线上由 nginx 统一入口：

```
浏览器 ── HTTP ──> nginx (web)
                     ├── /                Vue SPA 构建产物
                     ├── /api/            ──> api:8000（FastAPI）
                     ├── /media/          ──> 媒体卷（只读）
                     ├── /admin/          ──> api:8000（sqladmin 后台）
                     └── /healthz /readyz ──> api:8000
                                                └── postgres:16
```

- **只有 `web` 对外暴露端口**，`api` 与 `postgres` 只在 compose 内部网络里。
- **单 worker 单副本**：API 与 APScheduler 采集器同进程。限流、读时缓存、调度都是
  进程内状态，扩 worker 会放大上游请求并重复执行采集任务。
- **上游两种来源**：Supercell 官方 API（查询、实时榜）与 War Report（赛季榜、阵容）。
- **缓存分层**：请求时旁路缓存（`meta.cache` 为 `HIT` / `MISS` / `STALE`），
  采集器定时批量落库；上游故障时可用旧数据降级，但业务态错误（未找到、不在战争中、
  战争日志私密）不会降级。
- **媒体与素材分离**：用户上传的阵型图进 `media` 卷，库里只存
  `/media/bases/YYYY/MM/...` 相对路径；Fankit 兵种图标是宿主机静态目录，
  不入镜像、不入版本库。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | Vue 3 `<script setup>` + TypeScript + Vite + Vue Router + Pinia + Element Plus + axios + Vitest |
| 后端 | Python 3.12 + FastAPI + SQLAlchemy 2.0 async + asyncpg + Alembic + APScheduler + sqladmin |
| 数据 | PostgreSQL 16 |
| 部署 | Docker Compose（nginx + uvicorn + postgres），HTTP-only，可选 HTTPS |

## 目录

| 路径 | 内容 |
| --- | --- |
| `backend/` | FastAPI 后端：路由、Supercell 客户端、缓存、采集器、数据模型、迁移与测试 |
| `backend/app/coc/fixtures/` | 无 Token 时使用的本地占位响应 |
| `backend/AGENTS.md` | 后端硬约束、环境陷阱与测试约定（改后端前先读） |
| `frontend/` | Vue 3 前端：页面、组件、API 封装、路由与样式 |
| `frontend/src/api/endpoints.ts` | **所有** URL 与查询参数名的唯一出处 |
| `deploy/nginx.conf` | 线上入口配置：静态托管 + `/api`、`/admin`、`/media` 反代 |
| `deploy/compose.sh` | 部署入口：从 `PUBLIC_BASE_URL` 推导端口，补素材图 |
| `docker-compose.yml` | 单机三容器栈：`web` + `api` + `postgres` |
| `.env.example` | 组合栈环境变量模板（含必填项说明） |
| `docs/deployment.md` | **部署权威文档**：逐项配置、验证、备份、HTTPS、排障 |
| `docs/superpowers/` | 设计规格与实施计划；与代码冲突时以代码为准，并记一条裁定 |
| `scripts/fetch_fankit_assets.py` | 下载 Fankit 图标到 `frontend/public/pictures/` |

## 快速开始

### 前置条件

- Python **3.12+**
- Node **`^20.19 || >=22.12`**
- PostgreSQL **16**（本地实例，或自行用容器起一个）

### 1. 后端

```bash
cd backend
cp .env.example .env          # Windows PowerShell：Copy-Item .env.example .env
```

在 `backend/.env` 里至少填好：

```dotenv
DATABASE_URL=postgresql+asyncpg://<用户>:<密码>@127.0.0.1:5432/<库名>
MEDIA_ROOT=./.media           # 阵型图片目录，必须是可写路径
PUBLIC_BASE_URL=http://127.0.0.1:8000
```

`COC_API_TOKEN` 留空即可启动**夹具模式**：不请求官方 API，由
`backend/app/coc/fixtures/` 的样本应答，接口契约与页面都能跑通。
注意它是必填字段（可以为空值），`.env` 里要保留 `COC_API_TOKEN=` 这一行。

```bash
mkdir -p .media               # 启动前建好，否则 /media 不挂载
alembic upgrade head          # 建表
python -m app.cli seed-dev-rankings   # 可选：灌入夹具排行，无 Token 时榜单才有数据
python -m app.cli import-game-data    # 可选：导入升级数据（2073 行）
python -m uvicorn app.main:app --reload --port 8000
```

### 2. 前端

```bash
cd frontend
npm install
npm run dev
```

打开 `http://localhost:5173`。开发服务器的 `/api` 与 `/media` 已代理到 `:8000`。
生产构建用 `npm run build`，产物在 `frontend/dist/`。

### 3. 后台

`http://localhost:8000/admin/` 使用 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 登录。
凭据只从环境变量读取，不入库，也没有 `create-admin` 命令。

## 配置

组合栈的配置集中在仓库根 `.env`（由 `.env.example` 复制）。**`.env` 不入版本库。**

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | ✅ | 数据库密码；缺失时 `compose up` 直接报错并点名变量 |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | ✅ | 后台登录凭据 |
| `ADMIN_SECRET_KEY` | ✅ | 后台 session 签名密钥，必须是随机值 |
| `PUBLIC_BASE_URL` | ✅ | 站点对外绝对地址，**同时决定对外端口** |
| `POSTGRES_DB` / `POSTGRES_USER` | — | 默认 `coc` |
| `COC_API_TOKEN` | — | Supercell Token；留空 = 夹具模式 |
| `COC_BASE_URL` | — | 留空走官方；无静态 IP 时填 RoyaleAPI 代理 |
| `COC_RATE_LIMIT` / `COC_TIMEOUT` | — | 默认 8 次/秒、15 秒 |
| `WARREPORT_BASE_URL` / `WARREPORT_TIMEOUT` | — | War Report 上游，默认可用；**不要写成空值** |
| `RATE_LIMIT_PER_MINUTE` | — | 每 IP 每分钟请求数，默认 60；探针豁免 |
| `LOG_LEVEL` | — | 默认 `INFO` |

生成随机密钥：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## API 概览

所有业务接口以 `/api/v1` 为前缀，统一响应体：

```json
{
  "data": {},
  "meta": { "cache": "HIT", "fetched_at": "...", "age_seconds": 0, "ttl_seconds": 300 }
}
```

- `meta.cache` 为大写的 `HIT` / `MISS` / `STALE`。
- 分页参数 `page`（默认 1）与 `page_size`（默认 20，上限 50；超限**截断**而非 422）。
- 对外限流默认 60 次/分钟/IP；`/healthz`、`/readyz` 不计入。

| 分组 | 主要接口 |
| --- | --- |
| 探针 | `GET /healthz`、`GET /readyz` |
| 玩家 | `GET /api/v1/players/{tag}`、`GET .../battles` |
| 部落 | `GET /api/v1/clans/search`、`GET /api/v1/clans/{tag}`、`.../members`、`.../warlog`、`.../currentwar`、`.../cwl` |
| 实时榜 | `GET /api/v1/locations`、`GET /api/v1/rankings/{kind}` |
| 赛季榜 | `GET /api/v1/rankings/warreport/seasons`、`GET .../seasons/{snapshot}/{kind}` |
| 阵容 | `GET /api/v1/armies` |
| 阵型 | `GET /api/v1/bases`、`POST /api/v1/admin/bases`（HTTP Basic） |
| 其他 | 公告、升级数据、投稿等，详见 `backend/app/api/routes/` |

## 数据来源与署名

- **查询与实时榜**：Supercell 官方 API。没有 Token 时自动切到本地夹具，
  页面与接口仍然可用，但数据是占位样本。
- **赛季榜与阵容**：War Report（[https://warreport.app](https://warreport.app)），无需 Key。
  **署名是使用条件**：赛季榜面板、阵容页与全站页脚三处都必须保留来源标注
  （`SourceNote.vue` / `MainLayout.vue`）。修改相关页面前先读 `docs/deployment.md` §12。
- **阵型素材**：由站长整理上传，来源链接随条目保存。

**Token 与密钥绝不入库**，只放在 `.env`；`.env.example` 只保留空占位。

## 测试与构建

```bash
# 后端（backend/）
python -m pytest -q            # 686 项
python -m uvicorn app.main:app --reload --port 8000

# 前端（frontend/）
npm run test                   # 185 项（Vitest）
npm run build                  # vue-tsc 类型检查 + 产物到 dist/
```

后端测试会自行执行 `alembic upgrade head`，因此先跑测试也能把表建好。
测试默认连接 `localhost:5433` 的 PostgreSQL，可用 `DATABASE_URL` 覆盖。

## 部署

> 以下只是速查。**完整步骤见 [`docs/deployment.md`](docs/deployment.md)**：
> `.env` 逐项说明、建表与导入验证、冒烟清单、备份恢复、HTTPS 实操、排障。

```bash
cp .env.example .env                  # 填必填项
./deploy/compose.sh sync-assets       # 补 Fankit 素材图（约 250 MB，只需宿主机有 python3）
./deploy/compose.sh up -d --build     # 启动三容器

# 首次部署：建表 + 导入升级数据
docker compose exec api alembic upgrade head
docker compose exec api python -m app.cli import-game-data

# 可选：没有真实 Token 时，让排行榜有演示数据
docker compose exec api python -m app.cli seed-dev-rankings
```

### 为什么用 `compose.sh` 而不是直接 `docker compose`

对外端口是 `PUBLIC_BASE_URL` 的一部分（写 `http://1.2.3.4:7788` 就是 7788），
而 compose 只能做整值插值，无法从 URL 里解析端口。`deploy/compose.sh` 负责
读 `.env` → 推导端口 → 转交 compose。

直接跑 `docker compose up -d` 不会报错，但会回落到 80 端口，导致
`PUBLIC_BASE_URL` 与实际端口不一致（典型症状是页面能开、阵型图全裂）。
改端口后记得放行防火墙与云安全组。

```bash
./deploy/compose.sh --print-port      # 查看推导出的端口
./deploy/compose.sh logs -f api
./deploy/compose.sh ps
```

### 素材图与媒体目录

- Fankit 图标在 `frontend/public/pictures/`（gitignored），由 `web` 容器只读挂载。
  缺少时页面不会报错，只会回落到首页，所以补图后要**看 Content-Type** 验证。
- 用户上传的阵型图在 `media` 卷；备份要连这个卷一起备。
- 改了卷挂载必须 `./deploy/compose.sh up -d web` 重建容器，`nginx -s reload` 不够。

## 已知限制

- **夹具数据是占位样本**：每份响应带 `_source` / `_todo` 自报身份；拿到真实 Token 后
  应替换为真实响应。
- **排行榜依赖采集写库**：`seed-dev-rankings` 只造演示数据，真实排名需要有效 Token
  与采集器运行。
- **单 worker 单副本**：横向扩展前需要先把限流、缓存、调度改成共享实现，
  并利用 `APP_ROLE` 拆分 API 与采集器。
- **以 PC 浏览器为主**：Element Plus 桌面布局，未做手机端响应式适配。
- **HTTPS 默认关闭**：配置开关与步骤已备好，需要域名与证书后按部署文档启用。
- **SQLAlchemy 锁定 `<2.1`**：不要放宽上限，原因见 `backend/AGENTS.md`。

## 设计文档

- 规格：`docs/superpowers/specs/2026-10-16-cocpersonal-design.md`
- 计划与联调记录：`docs/superpowers/plans/2026-10-16-cocpersonal-mvp.md`
- 赛季榜 / 阵容：`docs/superpowers/specs/2026-10-23-warreport-data-design.md`
- 阵型功能：`docs/superpowers/specs/2026-11-04-coc-base-layouts-design.md`
