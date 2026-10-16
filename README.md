# COCPersonal

《部落冲突》查询站：**查询**（玩家 / 部落档案）+ **排行榜**（部落 / 玩家 / 都城 / 部落基地 / 玩家基地）。
浏览器网页（Vue 3 SPA），后端沿用 COCBack（FastAPI + PostgreSQL），单机 Docker Compose 部署。

> 这不是微信小程序项目。父目录 `MiniProgram/` 下的小程序版不在本仓库内 —— 本仓库是
> 「前端重写为网页 + 后端同仓」的独立项目。

## 目录

| 路径 | 内容 |
| --- | --- |
| `backend/` | 后端：FastAPI + SQLAlchemy 2.0 async + PostgreSQL + alembic + APScheduler。**整体搬自 COCBack**。其硬约束、环境陷阱、测试约定见 **`backend/AGENTS.md`**；运维（备份 / 证书 / 排障）见 `backend/docs/deployment.md` |
| `frontend/` | 前端：Vue 3 + Vite + TypeScript + Element Plus + Vue Router + Pinia + axios + Vitest |
| `deploy/nginx.conf` | 对外入口：托管 SPA 静态文件 + 反代 `/api`、`/admin`、`/media`、探针 |
| `docker-compose.yml` | 单机三容器栈：`web`（对外 80）+ `api`（内部 8000）+ `postgres` |
| `.env.example` | 组合栈的环境变量模板（**含必填项说明**） |
| `docs/superpowers/` | 设计规格与实施计划 —— **本仓库的权威**，与代码冲突时以代码为准并记一条裁定 |

## 本地开发（Windows）

前置：Python 3.12、Node `^20.19 || >=22.12`（开发机为 24）、PostgreSQL 16。

本机用的是**免安装 PostgreSQL**：`C:\pgportable`，监听 `127.0.0.1:5433`，trust 认证。
这不是洁癖，是没得选 —— 本机 CPU 虚拟化在固件层被关闭，Docker Desktop 与 WSL2 都不可用
（来龙去脉见 `backend/AGENTS.md` 的 R12）。

```powershell
# 0) 数据库就绪
C:\pgportable\pgsql\bin\pg_isready.exe -h 127.0.0.1 -p 5433 -U postgres

# 1) 后端
cd backend
Copy-Item .env.example .env        # 填值；COC_API_TOKEN 留空 = 夹具模式（见下）
alembic upgrade head               # 建表（首次、或迁移有更新时）
python -m app.cli seed-dev-rankings # 灌入夹具排行（无 Token 时排行榜才有数据）
python -m uvicorn app.main:app --reload --port 8000

# 2) 前端（另开一个终端）
cd frontend
npm install
npm run dev                        # http://localhost:5173（/api 已反代到 :8000）
```

浏览器打开 `http://localhost:5173`，导航只有「查询」和「排行榜」两项
（投稿 / 公告 / 后台入口已按设计剥离，后端代码仍在）。

### 测试与构建

```powershell
cd backend;  python -m pytest -q     # 494 passed
cd frontend; npm run test            # 32 passed（Vitest）
cd frontend; npm run build           # vue-tsc 类型检查 + 产物到 frontend/dist/
```

后端测试会自动跑 `alembic upgrade head`，所以「先跑测试」也能把表建好。

## 部署（Docker Compose，Linux 单机）

只有 `web` 映射端口，`api` 与 `postgres` 都只在 compose 内部网络里。

```bash
cp .env.example .env          # 填 POSTGRES_PASSWORD、ADMIN_USERNAME/PASSWORD/SECRET_KEY、PUBLIC_BASE_URL
docker compose up -d --build

# 首次部署：建表 + 导入升级数据（空库的升级接口只返回空列表）
docker compose exec api alembic upgrade head
docker compose exec api python -m app.cli import-game-data

# 可选：还没有真实 Token 时，让排行榜有数据可看
docker compose exec api python -m app.cli seed-dev-rankings
```

然后访问 `http://<服务器IP>/`。

排障：

```bash
docker compose ps
docker compose logs -f api
docker compose logs -f web
docker compose exec api alembic current
```

`POSTGRES_PASSWORD` / `ADMIN_USERNAME` / `ADMIN_PASSWORD` / `ADMIN_SECRET_KEY` /
`PUBLIC_BASE_URL` 五项用 `${VAR:?}` 保护 —— 没填会在 `docker compose up` 时**直接报错并
点名缺哪个变量**，不会带着空密码起来。`ADMIN_SECRET_KEY` 必须是随机值：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### HTTPS 开关（默认关闭）

当前是 **HTTP-only**（无域名、无证书）。要上 HTTPS 不用改任何代码，改配置即可：

1. `docker-compose.yml` 的 `web` 加端口 `- "443:443"`，并加只读挂载 `- ./deploy/certs:/etc/nginx/certs:ro`
2. 取消 `deploy/nginx.conf` 末尾那段注释掉的 `443 ssl` server，把它的 location 段按注释补齐
3. 80 端口的 server 里改成 `return 301 https://$host$request_uri;`
4. 证书续期仿照 `backend/deploy/certbot-renew.sh` 写一份

## 数据与夹具（还没有真实 Token 时）

`COC_API_TOKEN` **留空或为占位值**时，后端不打官方 API，改由 `backend/tests/fixtures/`
的本地样本应答（`backend/app/coc/devfixtures.py` 的 `FixtureTransport`）。这样在没有
Supercell Token 的情况下，整站也能跑通、且仍然走真实的后端响应契约。

⚠️ 这些样本是**手搓占位数据**，每个都带 `_source` 与 `_todo` 两个键自报身份；
拿到真实 Token 后要换成真实响应。排行榜数据来自 `seed-dev-rankings` 造的种子，
不是真实榜单。

拿到真实 Token 后：在 `.env` 里填 `COC_API_TOKEN`（**绝不入库**）。服务器没有静态 IP
时同时填 `COC_BASE_URL=https://cocproxy.royaleapi.dev/v1`，并把 Supercell key 的
Allowed IP 填代理的 `45.79.218.79`（不是服务器 IP）。

## 已知限制

- **`docker compose up` 从未在本机跑过**：本机 Docker 不可用，这里只验证到配置与构建产物
  的正确性（69 项静态校验 + 镜像构建所需的文件齐备）。**第一次 `up` 必须在 Linux 机器上做。**
- **浏览器 DOM 手测未在本机完成**：本机桌面浏览器被系统级 AdGuard 代理过滤，会对
  `:5173` 的模块请求返回 502 / 截断响应，页面渲染不出来。同一批静态资源用 `curl` 取是
  完整的（入口 bundle 约 1.0 MB，未截断），所以是环境问题而非代码问题。详见
  `docs/superpowers/plans/2026-10-16-cocpersonal-mvp.md` 的「联调记录」。
- **排行榜依赖采集写库**：种子脚本只造夹具数据；真实排名需要 Token + 采集器。
- 前端只按 PC 浏览器设计（Element Plus 桌面端），没有做手机端响应式。

## 设计文档

- 规格：`docs/superpowers/specs/2026-10-16-cocpersonal-design.md`
- 计划：`docs/superpowers/plans/2026-10-16-cocpersonal-mvp.md`（含「联调记录」）
