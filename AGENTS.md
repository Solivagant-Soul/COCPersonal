# AGENTS.md

本仓库 = 《部落冲突》查询站 **COCPersonal**：网页前端（Vue 3）+ 后端（整体搬自 COCBack）。
日常开发、构建的说明在 **`README.md`**，部署的权威文档是 **`docs/deployment.md`**
（README 只留速查）。这里只留「必须知道、否则会踩坑」的部分。

## 仓库现状

- 单仓两顶级目录：`backend/`（FastAPI + SQLAlchemy async + PostgreSQL）、`frontend/`（Vue 3 + Vite + TS）。
  部署资产在 `deploy/`、`docker-compose.yml`、`.env.example`。
- 远程 `origin` = `https://github.com/Solivagant-Soul/COCPersonal.git`，默认分支 `main`，**直接在 main 上开发**。
- 权威文档：`docs/superpowers/specs/2026-10-16-cocpersonal-design.md`（规格）与
  `docs/superpowers/plans/2026-10-16-cocpersonal-mvp.md`（计划 + 联调记录）。
  与代码冲突时以代码为准，并记一条裁定再往下走。

## 命令

```powershell
# 后端（backend/ 下）
python -m pytest -q                                  # 全量 501 个测试
python -m uvicorn app.main:app --reload --port 8000  # 起服务（需 backend/.env）
alembic upgrade head                                 # 建表（测试会自动跑，一般无需手动）
python -m app.cli seed-dev-rankings                  # 灌夹具排行（无 Token 时排行榜才有数据）
python -m app.cli import-game-data                   # 升级数据，应产出 2073 行

# 前端（frontend/ 下）
npm run test      # Vitest，36 个
npm run build     # vue-tsc 类型检查 + 产物到 dist/
npm run dev       # :5173，/api 已反代到 :8000
```

**后端有自己的 AGENTS.md（`backend/AGENTS.md`），那是后端的权威**：硬约束（`--workers 1`、
`sqlalchemy<2.1`、`meta.cache` 大写、`page_size` 截断而非 422）、环境陷阱（唯一可用 bash 是
`D:\Program Files\Git\bin\bash.exe`；本机虚拟化在固件层关闭，Docker/WSL2 不可用，测试库改用
`C:\pgportable` 的 `127.0.0.1:5433`）、测试约定（异步 `client`、`asyncio_mode=auto`）。
改后端任何东西之前先读它。

## 目录边界

- `backend/` 与 `frontend/` 是两个独立工程，各自有自己的依赖与命令，**不要**在前端里引后端源码，反之亦然。
- 前端与后端只通过 HTTP 契约耦合，契约摘要见规格 §10。
  前端所有 URL 与查询参数名只允许出现在 `frontend/src/api/endpoints.ts` 一处，页面不拼字符串。
- `deploy/nginx.conf` 是**部署侧**配置；本地开发走 Vite 的 `server.proxy`，两者互不影响
  （改了一处记得看另一处是否需要同步）。
- `.env` 均**不在版本库**（根 `.env` 与 `backend/.env` 都已被忽略）。密钥绝不入库，
  `.env.example` 只放空值占位。

## Git 工作流（强制）

- **每次修改都要及时提交到本地 git**（用户明确要求）。完成一个可验证的小改动就 `git commit`，
  不要攒大量改动一次性提交。
- 提交信息用中文 + conventional prefix（`feat:` `fix:` `test:` `chore:` `docs:`），**一个任务一个提交**。
- **默认只提交到本地；仅当用户明确要求时才 `git push`。**

## 未完成的欠账（不要以为"全绿即全好"）

- **`docker compose up -d` 从未在本机跑过**（本机 Docker 不可用）。部署资产只做到静态校验，
  第一次真实 `up` 必须在 Linux 机器上做。
- **浏览器 DOM 手测未在本机完成**：桌面浏览器被系统级 AdGuard 过滤，`:5173` 的模块请求会
  502 / 被截断。换机器或临时关掉 AdGuard 即可补上。
- **`backend/tests/fixtures/` 四份样本是手搓占位**（带 `_source` / `_todo` 自报身份），
  拿到真实 Supercell Token 后要换掉。
- **排行榜是夹具种子数据**，真实排名需要 Token + 采集器。
