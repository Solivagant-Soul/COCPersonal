# AGENTS.md

COC 微信小程序后端（FastAPI + SQLAlchemy 2.0 async + PostgreSQL）。一期做查询、我的、
投稿；二期做阵容、阵型；爬虫另立项目。设计与实施依据 `docs/superpowers/` 下的规格与
计划，**它们是本仓库的权威**；代码与配置冲突时以代码为准，代码与规格冲突时记一条裁定
再往下走。

## 命令

```powershell
python -m pytest -q                                  # 全量测试（默认即可用，无需 venv）
python -m pytest tests/coc/ -q                       # 单个目录
python -m pytest tests/db/test_dim_models.py::test_x # 单个用例
python -m pytest -q --no-header -p no:cacheprovider  # 输出更干净

# 数据库测试前置（conftest 已自动跑 alembic upgrade head，通常无需手动）
alembic upgrade head                                 # 只在手动查 schema 时需要
python -m pytest tests/db/ -q
```

**本机测试库 = 免安装 PostgreSQL 16.4，不是 Docker。** 位置 `C:\pgportable`，
监听 `127.0.0.1:5433`，数据目录 `C:\pgportable\data`，trust 认证。若端口不通，先起服务：

```powershell
C:\pgportable\pgsql\bin\pg_isready.exe -h 127.0.0.1 -p 5433 -U postgres
# 未起则（Start-Process 分离启动，不要用 pg_ctl start——它在 Windows 上会阻塞终端）
Start-Process "C:\pgportable\pgsql\bin\postgres.exe" `
  -ArgumentList "-D","C:\pgportable\data","-p","5433","-h","127.0.0.1" -WindowStyle Hidden
```

**这个选择的由来（R12）**：本机 CPU 虚拟化在 BIOS/UEFI 里被关闭
（`VirtualizationFirmwareEnabled: False`），WSL2 与 Docker Desktop 都不可用，且
`wsl --shutdown` 与重启均无效。`docker-compose.test.yml` 仍保留原样作为部署侧资产，
虚拟化恢复后两条路都能用。

**本地未建 `.env` 时，alembic / app.cli 这类独立进程会直接失败**：它们不走
`tests/conftest.py`，`get_settings()` 的三个必填字段拿不到。做法是复制 `.env.example`
为 `.env` 并填值（该文件已被忽略，不入库）。

提交信息用中文 + conventional prefix（`feat:` `fix:` `test:` `chore:` `docs:`），
**一个任务一个提交**。

## 环境陷阱（真实踩过，代价高）

- **本机唯一的可用 bash 是 `D:\Program Files\Git\bin\bash.exe`。** PATH 上的 `bash` 是 WSL
  转发桩且 WSL 未安装，任何 `bash xxx/script.sh` 都会报
  `execvpe(/bin/bash) failed`。superpowers 技能的脚本（task-brief / review-package 等）
  必须用上面的 Git Bash 解释器跑。
- **本机 CPU 虚拟化在固件层被关闭**（`VirtualizationFirmwareEnabled: False` /
  `SLAT: False`），因此 **WSL2 与 Docker Desktop 完全不可用**，且 `wsl --shutdown` 与重启
  都无效。这正是本机改用 `C:\pgportable` 免安装 PostgreSQL 的原因（见「命令」）。
  若在别的机器上撞见 `execvpe(/bin/bash) failed` 或
  `npipe:///./pipe/dockerDesktopLinuxEngine` 报错，先查虚拟化开关，别去 repair WSL ——
  那不是 WSL 的故障。
- **`migrations/env.py` 必须 import 模型，否则 alembic 静默生成空迁移。** 只 import
  `Base` 时 `Base.metadata` 为空，`alembic revision --autogenerate` 会"成功地"生成一个
  `pass` —— 不报错、不失败，只是什么都没建。**每次 autogenerate 后都要核一遍
  `op.create_table` 的数量是否符合预期。**
- `alembic upgrade head` 在未 stamp 的空库上报 "Target database is not up to date"，
  需先 `alembic stamp head`。另外 `migrations/script.py.mako` 模板是必需的，
  手动建 `migrations/` 目录时容易漏。
- **SQLAlchemy 已锁定 `<2.1`（`pyproject.toml`），不要放宽。** 2.1.x 官方 wheel 里的
  `sqlalchemy/sql/_util_cy.cp312-win_amd64.pyd` 在本机加载失败（`WinError 4551`，
  逐字节比对确认与官方 wheel 完全一致、干净路径下同样被拦，非安装残缺）。
  上限一放开，Task 20 的 Docker `pip install .` 会解析到 2.1.x，产出一个 import 即崩的镜像。
- **生产镜像里只有 `pyproject.toml` 声明过的依赖，本机环境却多得多。**
  「本机装着、但不属于任何已声明依赖的孤儿包」会让本机测试全绿、却让容器在**导入期**
  就 `ModuleNotFoundError` → `uvicorn` 退出码 1 → 容器无限重启。真实踩过：`itsdangerous`
  只挂在 `fastapi` 的 `extra == "all"` 与 `sqladmin` 的 `extra == 'auth'` 下，
  而 `pip install .` **不装 extras** —— 它却是 SQLAdmin 认证经 starlette SessionMiddleware
  的硬需求，漏声明就等于镜像起不来。
  守门测试：`tests/test_runtime_deps.py`（把孤儿包屏蔽掉再 import 一次应用，复现镜像环境）。
  **加了新依赖必须进 `dependencies`；靠别人的 extra 顺带装到的东西不算。**
- **夹具是运行时资产，必须住在包内并声明成 package-data。**
  `app/coc/devfixtures.py`（无 Token 时的上游替身）与 `app/devseed.py`（灌排行种子）
  都在**运行时**读夹具，而生产镜像只装 `app/` 包 —— 夹具放 `tests/` 下时，镜像里
  两者双双 `FileNotFoundError`：**无 Token 的部署等于所有上游读取全 500**，
  `seed-dev-rankings` 也跑不了（已真实发生过两次）。
  现在夹具在 `app/coc/fixtures/`，路径由 `devfixtures.FIXTURES_DIR` 唯一定义
  （`devseed` 直接复用它，别再自己算路径），并由 `pyproject.toml` 的
  `[tool.setuptools.package-data]` 声明随 wheel 分发。
  守门测试：`tests/test_runtime_deps.py::test_fixtures_are_packaged_with_the_app`。
- **测试环境变量必须在任何 `app.*` 被 import 之前设置。** `get_settings()` 带 `lru_cache`，
  首次调用即固化。`tests/conftest.py` 因此在模块顶层（import 任何 app 模块之前）调
  `set_test_env()`；fixture 里那次调用是冗余兜底。改动它之前先读那段注释。
- **`alembic.ini` 必须保持纯 ASCII。** Windows 上 `configparser` 按 GBK 解码，任何
  中文注释都会让它报 `UnicodeDecodeError: 'gbk' codec can't decode byte`。
  迁移用 `alembic revision --autogenerate -m "..."`，message 用英文。
- **`migrations/env.py` 必须走异步引擎**（`async_engine_from_config` + `run_sync`）。
  对 asyncpg URL 用同步 `create_engine` 会得到 `MissingGreenlet: greenlet_spawn
  has not been called`。
- `session` fixture 在**每个用例前后各截断一次所有表**（`TRUNCATE ... CASCADE`）。
  因此同一用例内不要依赖上一个用例留下的数据，也别指望 `RESTART IDENTITY` 之外的自增连续性。
- **模块级单例 `engine` 必须在每个用例后 `dispose()`**（根 conftest 已做）。
  pytest-asyncio 默认**函数级**事件循环，不 dispose 的话上一个用例的连接池仍绑在已关闭的
  循环上，下一个报 `'NoneType' object has no attribute 'send'`。特征是「单独跑能过、
  连着跑才炸」，极易误判为 flaky。
- 想在同一个 session 里验证唯一约束，**不要** `session.add()` 同一主键的第二个对象
  （identity map 会在 flush 前就拦掉，约束根本到不了数据库，成了假测试），
  用 `session.execute(insert(Model).values(...))` 走 ORM insert。
- `python -m pytest` 与裸 `pytest` 有别：`pyproject.toml` 的 `pythonpath = ["."]` 让两者都能
  找到 `app` 包，但**不要**删掉这一行，删了裸 `pytest` 立刻 `ModuleNotFoundError`。

## 测试约定（刻意偏离常见默认）

- `client` fixture 是**异步**的：`httpx.AsyncClient` + `ASGITransport`。
  **所有**使用 `client` 的测试一律 `async def` + `await client.get(...)`。
  **禁止同步 `TestClient`** —— 它自带独立事件循环，与异步 `session` fixture（asyncpg
  连接绑定事件循环）无法共存，会在 Task 9 起同时用两者的测试里报
  `attached to a different loop`。
- `asyncio_mode = "auto"`，因此 async 测试**不要**加 `@pytest.mark.asyncio`。
- **`session` / `engine` fixture 只存在于根 `tests/conftest.py`。** 不得另建
  `tests/db/conftest.py` —— pytest 的 fixture 按「测试文件所在目录」向上查找，
  子目录 conftest 对 `tests/api/` 不可见，而 Task 9 / 13 的测试需要同时拿到
  `client` 与 `session`。
- `app/` 下的包有 `__init__.py`，`tests/` 下的目录**没有**（跟 Task 1 的既有约定一致）。
- 新增测试要能"看它失败"。若某个测试在错误实现上也能通过，它是假测试，需重写。
- 写异步限流/缓存代码时注意：睡够延迟后必须**回到循环重新检查**，不能直接返回 ——
  等待期间别人可能已取走那枚令牌。令牌桶等待期间也不得持锁。

## API 契约硬规矩（规格 §6，前端直接依赖）

- 统一响应体为 `{"data": ..., "meta": {"cache": ..., "fetched_at", "age_seconds",
  "ttl_seconds"}}`。
- **`meta.cache` 的值是大写**：`HIT` / `MISS` / `STALE`（§6.1 与 §3 数据流均如此）。
  小写会直接破坏前端契约。
- 对外分页：`page` 默认 1，`page_size` 默认 20，**上限 50 且超限截断为 50**。
  不要用 pydantic `le=50` —— 那会让 `?page_size=500` 返回 422，而设计意图是返回 200 + 截断。
- 对外限流 60 次/分钟/IP；`/healthz` 与 `/readyz` **不计入**限流桶（容器探针要无限调用），
  但验证限流的测试必须打非豁免端点（如 `/api/v1/locations`），否则永远拿不到 429。

## 架构边界（文件名看不出来的）

- **单进程一体**：uvicorn 单 worker + 同进程 APScheduler。生产 `Dockerfile` 的
  `CMD` 固定 `--workers 1`，不要为了"性能"加 worker。拆进程的预留位是
  `APP_ROLE`（`all`/`api`/`collector`）与 `RateLimiter` 接口，**现在就用，不要提前拆**。
- `app/coc/` 是**唯一**允许与 Supercell 耦合的模块；`app/collector/` **不得** import
  FastAPI（否则部署时无法单独起 collector 角色）。
- 官方数据走两条路：读时旁路缓存（`app/cache/`）+ 定时批量采集（`app/collector/`）。
- `meta.cache = STALE` 表示回源失败但有旧数据，此时仍返回 HTTP 200。
- 业务态错误（`notFound` / `notInWar` / `privateWarLog`）**绝不降级为 STALE**，必须冒泡。
  故障态（`CocThrottled`/`CocUpstreamError`/`CocTimeout`）与 `CocAccessDenied` 才可降级。
- `CocAccessDenied` 是 `CocError` 的**直接**子类、不得归到 `CocFaultError` 下
  （否则会被重试循环白烧 3 次令牌桶额度）；但它在缓存层仍可降级为 STALE，
  因为"可降级"与"可重试"是两个正交决策。

## 数据模型不变量（§5.6，改动前先读）

- **业务表不建外键到维表**（`clans.location_id`、`clan_members.league_tier_id` 只建索引）。
  只给从属关系建 FK 且 `ON DELETE CASCADE`。
- **榜单刷新一律「按 scope 全量替换」**：同事务内 `DELETE` + 批量 `INSERT`，
  禁止逐条 upsert —— 否则掉榜的条目会永远残留。
- 所有官方时间戳按 UTC 存 `TIMESTAMPTZ`，**禁止裸 naive datetime**（服务器在大陆，
  naive 会让 TTL 判定偏差 8 小时）。mapper 的 `now` 一律由调用方注入，不在内部取时间。
- tag 大小写不敏感：入库/比较前统一 `app.coc.tags.normalize_tag()` 归一化为 `#大写`，
  发请求前用 `quote_tag()` 得到 `%23...`。**不得自行 `strip().upper()`。**
- `users` 与 `user_clan_subscriptions` 是二期账号功能的地基，归 Task 6 的实体表迁移建，
  现在不要为它们写读写逻辑。

## 脚本与运维

- **Supercell Token 绝不入库**，只在 `.env`；`.env.example` 只放空值占位
  （`tests/test_deployment_config.py` 会断言 `COC_API_TOKEN=` / `ADMIN_PASSWORD=` 后为空）。
- 后台管理员凭据走环境变量 `ADMIN_USERNAME` / `ADMIN_PASSWORD`，**不入库、无 `create-admin` 命令**。
- 升级数据导入：`python -m app.cli import-game-data`，应产出 2073 行
  （troop 599 / spell 111 / hero 513 / equipment 850）。

### 上游接入（R26、代理域名 R28）

- 默认直连官方 `https://api.clashofclans.com/v1`（`app/coc/client.py` 的 `BASE_URL`）。
- **线上走 RoyaleAPI 代理**：`COC_BASE_URL=https://cocproxy.royaleapi.dev/v1`，
  且 Supercell key 的 Allowed IP 填**代理的 `45.79.218.79`**（不是服务器 IP）。
  代理只换域名转发，路径/鉴权/响应形状不变，所以 client 的协议校验、
  错误映射、降级规则全部照旧。
- `COC_BASE_URL` 留空回落到官方（`Settings._default_base_url`）。哪天有静态 IP，
  清空这行即可切回，代码不用动。
- 代理是共享免费服务，**不要调高 `COC_RATE_LIMIT`**。
- 403 的含义随接入方式变化：直连时 = 服务器 IP 不在白名单或 Token 过期；
  走代理时 = 代理 IP 被移出白名单、Token 过期，或代理本身限流。语义不变：
  `CocAccessDenied` 仍是环境级故障，可降级为 STALE，不参与重试。

## 工作流与在飞状态

- **直接在 `main` 上开发**（人工伙伴于 Task 3 后拍板：合并分支并回到主干）。
  历史上前 3 个任务曾在 `.worktrees/coc-phase1` 分支上做，后以快进合并回 main
  并删除该分支与 worktree；那种隔离方式现已停用，不要自作主张再建 worktree。
- **有远程 `origin`**（`https://github.com/Solivagant-Soul/COCBack.git`），
  但 **push 由人工伙伴决定**，不要自作主张推。本地与远程当前同步。
- 计划的执行进度与全部裁定记录在
  `.superpowers/sdd/2026-10-08-coc-backend-phase1/progress.md`（gitignored 的临时区，
  但对恢复上下文极关键，**读它，不要重建它**）。
  **当前：20 个任务（Phase A/B）全部完成并提交，全量 486 个测试通过。**
  收尾状态见账本末条 R27。
- 规格与计划分别在 `docs/superpowers/specs/2026-10-08-coc-backend-design.md` 与
  `docs/superpowers/plans/2026-10-08-coc-backend-phase1.md`（20 个任务，Phase A/B）。
  改计划要同步改账本里的裁定编号，否则后续任务的 brief 看不到你的决定。

### 未完成的欠账（都要真实环境，本机做不了）

一期代码已完成，但以下**验收/资产项仍挂着**，不要误以为"全绿即全好"：

- **`app/coc/fixtures/` 五份响应样本是手搓占位**，每个带 `_source` + `_todo` 两个键自报身份。
  拿到真实 Supercell Token 后要换成真实响应，并删掉 `tests/test_fixture_samples.py`
  里的 `test_samples_are_marked_placeholders`。
- **验收项 A2 / B2**（`docker compose up -d` 从零启动）：本机虚拟化在固件层关闭（R12），
  Docker/WSL 不可用，只能用 `C:\pgportable` 的本地 PG 替代；**这条已于 2026-10-20
  在一台 Linux 服务器上真实跑通**（首跑还揪出两个部署缺陷：镜像缺 `itsdangerous`、
  夹具没随包分发，见计划文档账本 Task 14 / Task 15）。本机仍然跑不了。
- **验收项 A3 / B5**（手动冒烟）与 **B4**（后台补 `name_zh`、录公告、审投稿）：
  需真实 Token 与真实数据。
- 本地 `.env` 未设 `ADMIN_USERNAME` / `ADMIN_PASSWORD`（代码按 `os.environ.get(..., "")`
  读，有空默认值、不会崩），因此**本地后台登录进不去** —— 只影响本地，不影响部署。
