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
python -m pytest -q                                  # 全量 639 个测试
python -m uvicorn app.main:app --reload --port 8000  # 起服务（需 backend/.env）
alembic upgrade head                                 # 建表（测试会自动跑，一般无需手动）
python -m app.cli seed-dev-rankings                  # 灌夹具排行（无 Token 时排行榜才有数据）
python -m app.cli import-game-data                   # 升级数据，应产出 2073 行

# 前端（frontend/ 下）
npm run test      # Vitest，125 个
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
- 前端与后端只通过 HTTP 契约耦合，契约摘要见规格 §11。
  前端所有 URL 与查询参数名只允许出现在 `frontend/src/api/endpoints.ts` 一处，页面不拼字符串。
- `deploy/nginx.conf` 是**部署侧**配置；本地开发走 Vite 的 `server.proxy`，两者互不影响
  （改了一处记得看另一处是否需要同步）。
- **部署一律用 `./deploy/compose.sh`（不是 `docker compose`）**：对外端口由
  `.env` 的 `PUBLIC_BASE_URL` 推导（compose 只能整值插值、没法在 YAML 里解析 URL）。
  直接跑 `docker compose up -d` 会**回落到 80 端口**，站点能开但投稿图片全裂、
  且无任何报错。详见 `docs/deployment.md` §2。
- **素材图（`frontend/public/pictures/`，gitignored）用 `./deploy/compose.sh sync-assets` 补**：
  它只跑宿主机上的 `python3`，不碰 docker、不需要 `PUBLIC_BASE_URL`。下载目标**必须**
  等于 compose 里 nginx 的挂载源，否则站点永远看不到新图（`backend/tests/test_root_deployment_assets.py`
  钉着这条）。详见 `docs/deployment.md` §14。
- `.env` 均**不在版本库**（根 `.env` 与 `backend/.env` 都已被忽略）。密钥绝不入库，
  `.env.example` 只放空值占位。

## Git 工作流（强制）

- **每次修改都要及时提交到本地 git**（用户明确要求）。完成一个可验证的小改动就 `git commit`，
  不要攒大量改动一次性提交。
- 提交信息用中文 + conventional prefix（`feat:` `fix:` `test:` `chore:` `docs:`），**一个任务一个提交**。
- **默认只提交到本地；仅当用户明确要求时才 `git push`。**

## 未完成的欠账（不要以为"全绿即全好"）

- **~~`docker compose up -d` 从未跑过~~** → **已在 Linux 服务器上完成首次真实 `up`**
  （2026-10-20）。首跑暴露并修掉了「镜像缺 `itsdangerous`」的部署缺陷（见账本 Task 14）。
  **本机仍无 Docker**（固件层关虚拟化），所以「改完部署资产后本机无法自证」这条约束依旧成立。
- ~~**浏览器 DOM 手测未在本机完成**~~ → **已补做通过**（2026-10-17，见计划文档 Task 9 Step 3）。
- **`backend/app/coc/fixtures/` 四份样本是手搓占位**（带 `_source` / `_todo` 自报身份），
  拿到真实 Supercell Token 后要换掉。
- **排行榜是夹具种子数据**，真实排名需要 Token + 采集器。
- **2026-10-22 起：排行榜只刷「全服（落库 scope 32000000）的部落榜与玩家榜」**。
  都城榜 / 部落基地榜 / 玩家基地榜已停采、路由已删（404）。详见
  `backend/AGENTS.md` 与规格里的裁定条目。
- **2026-10-26 更正：`32000000` 在官方 API 里是「欧洲」，不是 Global**（它的
  `isCountry` 同样是 false，所以别拿这个字段判断全服）。**部落榜与玩家榜的上游
  路径参数都必须是虚拟地区 `global`** —— `/locations/32000000/rankings/clans`
  虽然返回 200，但 `items` 恒为空，这正是线上「部落榜一直是空的」的根因。
  **落库 scope 与 API / 前端契约仍统一是 32000000**，只有上游路径参数用
  `global`（见 `backend/app/collector/jobs/rankings.py` 的 `_UPSTREAM_LOCATION`），
  两者别混成一个值。
- **2026-10-23：赛季榜与阵容数据来自 War Report（https://warreport.app，无需 Key）**。
  **署名是使用条件**：赛季榜面板、阵容页、全站页脚三处都要保留（`SourceNote.vue` /
  `MainLayout.vue`）。**改这些相关页面前先读 `docs/deployment.md` §12**。
- **前端是深色主题**（参照 coc.daozishule.cn）：改样式时用 `main.css` 里的
  主题变量（`--surface-*` / `--text-*` / `--accent-gold`），**别写死颜色**。
  Element Plus 的深色靠覆盖它的 CSS 变量实现 —— 新加组件时要确认它在深色下
  正常，别只改 body 背景。

- **2026-11-05：阵型页已可浏览 / 上传**。图片在 `media` 卷（本地 `backend/.media`），
  入库只存 `/media/bases/YYYY/MM/...`；上传接口 `POST /api/v1/admin/bases` 用
  HTTP Basic（`ADMIN_USERNAME` / `ADMIN_PASSWORD`，任一为空一律 401），**上传即发布**。
  批量导入走项目 skill `.opencode/skills/coc-base-import/`：B 站 cookie 放
  `.secrets/bilibili-cookies.txt`（已忽略，绝不入库），图片超 5 MiB 会被 413。
  改这块前先读 `docs/deployment.md` §15。
