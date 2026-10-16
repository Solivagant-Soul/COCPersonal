# COC 小程序后端 —— 一期实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一个部署在 Linux 单机的 FastAPI 后端，为 COC 微信小程序提供部落/玩家查询、六类排行榜、升级数据、公告与投稿五组 API，并附带单管理员 SQLAdmin 后台。

**Architecture:** 单进程一体 —— uvicorn 单 worker 与 APScheduler 调度器同进程，`APP_ROLE` 控制角色。 Supercell 访问全部收敛在 `app/coc/`（httpx + 令牌桶 + 指数退避），采集编排全部收敛在 `app/collector/`（不依赖 FastAPI）。官方数据走「读时旁路 + 定时批量」双路径写入 PostgreSQL；内容数据走「后台录入 + npm 数据集导入 + 用户投稿审核」。

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy 2.0 (async) · asyncpg · Alembic · PostgreSQL 16 · APScheduler · SQLAdmin · httpx · pytest + pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-10-08-coc-backend-design.md`

---

## Global Constraints

以下约束适用于本计划每一个任务，不再逐任务重复：

- **Python 3.12**，仅本机已装版本。所有新代码使用现代类型标注（`X | None`，不用 `Optional`）。
- ** Supercell API 基址** `https://api.clashofclans.com/v1`，认证头 `Authorization: Bearer $COC_API_TOKEN`。
- **Token 绝不入库**，只在 `.env` 中，`.env.example` 只放占位空值。
- **对外限流 60 次/分钟/IP**（nginx 层 + 应用层），对外分页 `page` 默认 1、`page_size` 默认 20、**上限 50（超限截断，绝不透传给官方）**。
- **对官方限流 8 req/s**（令牌桶），**单请求最多重试 3 次，退避 1s → 2s → 4s**。
- **业务态错误绝不重试**：`notFound` / `notInWar` / `privateWarLog` 直接转 HTTP 码。
- **榜单刷新一律「按 scope 全量替换」**：`DELETE` + 批量 `INSERT` 同一事务，禁止逐条 upsert。
- **业务表不建外键到维表**；从属关系（`clan_members.clan_tag`、`upgrade_route_steps.route_id` 等）建 FK 且 `ON DELETE CASCADE`。
- **所有官方时间戳按 UTC 存 TIMESTAMPTZ**，解析时必须带时区，禁止裸 `datetime`。
- **CI 不得调用真实 Supercell API**。真实调用只在手动冒烟测试中执行。
- **每个任务结束必须提交**，提交信息用中文，格式 `feat:` / `fix:` / `test:` / `chore:` / `docs:`。
- **测试风格（R2 裁定，全局约定）：** `client` 是**异步** fixture（`httpx.AsyncClient` + `ASGITransport`），因此**所有**使用 `client` 的测试一律写 `async def` 并 `await client.get/post(...)`。**禁止使用同步 `TestClient`** —— 它自带独立事件循环，与异步的 `session` fixture（asyncpg 连接绑定事件循环）无法共存，会在 Task 9 混用两者的测试里报 `attached to a different loop` 一类错误。测试靠 `asyncio_mode = "auto"` 自动识别 async 测试函数，无需 `@pytest.mark.asyncio`。
- 数据库测试需要 PostgreSQL：`docker compose -f docker-compose.test.yml up -d`（Task 3 建立）。测试环境变量统一用 `DATABASE_URL` 指向测试容器（端口 5433），不得让测试连到其它库（R6 裁定）。

---

## Review Focus

规格未明确规定、但真实使用中极易出问题、且**每个任务都必须自行覆盖**的五个输入类别：

1. **tag 大小写与 `#` 编码** —— COC 标签大小写不敏感。用户输入 `#2pp`、数据库键为 `#2PP`，若不归一化会生成重复行；且 `#` 必须编码为 `%23` 才能发请求。小程序用户从输入法/粘贴产生的标签大小写随机。
2. **时区** —— 官方返回 `2024-01-15T08:30:00.000Z`（UTC 毫秒 ISO8601）。服务器若跑在中国大陆，若存为 naive datetime，TTL 判定会偏差 8 小时，导致数据永远判定为「新鲜」或永远过期。
3. **Token 过期 / 公网 IP 变更导致的全局 403** —— 这是生产环境最可能发生的故障，且**不是** `accessDenied.invalidIp` 而是 `accessDenied`。此时所有查询同时失败，但库里有旧数据：期望行为是逐条降级为 `STALE` 并告警，而不是让用户看到一片 502 或空数据。
4. **分页参数越界** —— `page_size=500` 必须截断为 50（官方只接受 1–50，透传会得到 `badRequest`）；`page=999` 应返回空列表而非 404 或报错。
5. **官方响应字段增删** —— Supercell 随时可能新增字段或对可选字段省略（如无部落时 `role` 缺失）。mapper 必须对未知字段和缺失的可选字段都不得抛异常。

---

# Phase A · 基建 + 官方数据管道 + 查询页

### Task 1: 项目骨架与健康检查

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `app/main.py`
- Create: `app/api/__init__.py`
- Create: `app/api/routes/__init__.py`
- Create: `app/api/routes/system.py`
- Create: `tests/conftest.py`
- Test: `tests/api/test_system.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `app.config.Settings` (pydantic-settings BaseSettings)，字段：`coc_api_token: str`、`database_url: str`、`app_role: str = "all"`、`coc_rate_limit: int = 8`、`coc_timeout: float = 15.0`、`media_root: str = "/data/media"`、`public_base_url: str`、`log_level: str = "INFO"`
  - `app.config.get_settings() -> Settings`（lru_cache 单例）
  - `app.main.create_app() -> FastAPI`（挂载全部路由）
  - `GET /healthz` → `200 {"status": "ok"}`

- [ ] **Step 1: 写失败测试**

`tests/api/test_system.py`：

```python
async def test_healthz_returns_ok(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

`tests/conftest.py` 提供 `client` fixture —— **必须是异步 `httpx.AsyncClient` 配 `ASGITransport`，不得用同步 `TestClient`**：

```python
@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
```

**为什么不能用 `TestClient`（R2 裁定，务必照办）：** `TestClient` 自带一个独立事件循环，而后续任务的 `session` 是异步 fixture 且 asyncpg 连接**绑定事件循环**。一旦 Task 9 在同一个测试里同时用到 `client` 与 `session`，就会跨循环复用连接并报错；届时返工要横跨 Task 1 与 Task 9 两个任务。现在花一行换成 `ASGITransport` 是最省事的一处修复。

同一 conftest 设置测试环境变量（`monkeypatch.setenv` 或 `os.environ`）：`COC_API_TOKEN=test-token`，以及 **`DATABASE_URL` 必须指向测试容器**（Task 3 建立，端口 5433 —— **R6 裁定：统一用 `DATABASE_URL` 这个名字，`TEST_DATABASE_URL` 只是文档别名，不得让测试连到别的库**）。Task 1 阶段尚无测试库，`DATABASE_URL` 可先留空占位，由 Task 3 补实。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/api/test_system.py::test_healthz_returns_ok -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: 写 `pyproject.toml`**

依赖固定：`fastapi>=0.115`、uvicorn、sqlalchemy>=2.0、asyncpg、alembic、httpx>=0.28、pydantic-settings、apscheduler>=3.10、sqladmin、python-multipart（SQLAdmin 表单需要）。开发依赖：pytest、pytest-asyncio。配置 `[tool.pytest.ini_options]` 设 `testpaths = ["tests"]` 与 `asyncio_mode = "auto"`。

- [ ] **Step 4: 实现 `app/config.py` 与 `app/main.py`**

`Settings` 字段名用小写下划线，pydantic-settings 通过 `env_prefix` 不设、直接同名映射环境变量（`COC_API_TOKEN` → `coc_api_token`），需显式声明 `model_config = SettingsConfigDict(env_file=".env")`。

`create_app()` 中 `app.include_router(system.router)`。

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/api/test_system.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add pyproject.toml .env.example app/ tests/
git commit -m "feat: 项目骨架、配置与健康检查"
```

---

### Task 2: 错误层次与令牌桶限流器

**Files:**
- Create: `app/coc/__init__.py`
- Create: `app/coc/errors.py`
- Create: `app/coc/ratelimit.py`
- Test: `tests/coc/test_errors.py`
- Test: `tests/coc/test_ratelimit.py`

**Interfaces:**
- Consumes: `app.config.Settings.coc_rate_limit`
- Produces:
  - `app/coc/errors.py`：`CocError(Exception)` 基类，字段 `reason: str`；子类 `CocBusinessError`、`ClanNotFound`、`PlayerNotFound`、`NotInWar`、`WarLogPrivate`、`CocFaultError`、`CocThrottled`、`CocUpstreamError`、`CocTimeout`、`CocAccessDenied`、`CocProtocolError`
  - `app/coc/ratelimit.py`：`RateLimiter` Protocol（`async def acquire(self) -> None`）；`MemoryRateLimiter(rate: int = 8, burst: int | None = None)`，`burst` 默认等于 `rate`；`async def close(self) -> None`

**类继承设计要点**（易被误改，先说清楚）：`CocAccessDenied` 必须是 `CocError` 的**直接**子类，不能继承 `CocFaultError` —— 那样会被客户端的重试循环自动重试 3 次，而 IP 白名单不匹配时重试完全无意义，只会把令牌桶白白烧光 3 次。但它**仍然可降级为 STALE**（见 Task 8 Step 3），因为降级与重试是两个正交的决策。

- [ ] **Step 1: 写失败测试**

`tests/coc/test_errors.py`：断言 `ClanNotFound`、`NotInWar`、`WarLogPrivate` 是 `CocBusinessError` 的子类；`CocThrottled`、`CocUpstreamError`、`CocTimeout` 是 `CocFaultError` 子类；`CocAccessDenied` 与 `CocProtocolError` 直接继承 `CocError` 而非任何上述中间类。

`tests/coc/test_ratelimit.py`：

```python
async def test_allows_rate_requests_within_one_second():
    limiter = MemoryRateLimiter(rate=8)
    start = time.monotonic()
    for _ in range(8):
        await limiter.acquire()
    assert time.monotonic() - start < 0.5
    await limiter.close()

async def test_tenth_request_waits():
    limiter = MemoryRateLimiter(rate=8)
    for _ in range(8):
        await limiter.acquire()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(limiter.acquire(), timeout=0.3)
    await limiter.close()
```

第二个测试用 `wait_for` 超时来断言「确实在等」而非精确计时 —— 避免脆弱的时序断言。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/coc/test_errors.py tests/coc/test_ratelimit.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.coc'`

- [ ] **Step 3: 实现 `errors.py`**

每个子类固定 `reason` 值，与官方 API 的 `reason` 字段一致：`notFound`、`notInWar`、`privateWarLog`、`requestThrottled`、`unknownException`、`requestAborted`、`accessDenied`、`accessDenied.invalidIp`。用类属性而非构造参数。

- [ ] **Step 4: 实现 `ratelimit.py`**

用 `asyncio.Lock` + 记录上次取令牌时间戳实现令牌桶。关键：`acquire()` 在令牌不足时**必须释放锁并 `await asyncio.sleep(剩余时间)`**，不可持锁睡眠 —— 否则会串行化所有并发请求。`close()` 需取消内部唤醒用的 `asyncio.Event` 等待者，避免测试结束时 pending task 警告。

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/coc/ -v`
Expected: PASS，且无 "Task was destroyed but it is pending" 警告

- [ ] **Step 6: 提交**

```bash
git add app/coc/ tests/coc/
git commit -m "feat: 错误层次与进程内令牌桶限流器"
```

---

### Task 3: 数据库基座与维表迁移

**Files:**
- Create: `docker-compose.test.yml`
- Create: `app/db/__init__.py`
- Create: `app/db/base.py`
- Create: `app/db/session.py`
- Create: `app/db/models.py`
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/versions/0001_dimension_tables.py`
- Modify: `tests/conftest.py`（**R1 裁定：`session` 与 `engine` 建在这里，不是 `tests/db/conftest.py`**）
- Create: `tests/db/test_dim_models.py`

**Interfaces:**
- Consumes: `Settings.database_url`
- Produces:
  - `app/db/base.py`：`Base(DeclarativeBase)`
  - `app/db/session.py`：`async def get_session() -> AsyncGenerator[AsyncSession, None]`（FastAPI 依赖）、`engine`、`async_sessionmaker`
  - `app/db/models.py`：`Location`、`LeagueTier`、`League`、`Label`、`Season` 五个 ORM 类，字段见规格 §5.1
  - `tests/conftest.py`：`session` 异步 fixture + `engine` + `pytest_sessionstart`/`function` 级建表与清表

**`session` fixture 为什么必须放根 `tests/conftest.py`（R1 裁定）：** 原计划写在 `tests/db/conftest.py`，但 pytest 的 fixture 按**测试文件所在目录**向上查找，`tests/db/conftest.py` 对 `tests/api/` 不可见 —— 而 Task 9 的 `test_stale_fallback_returns_200_not_502` 需要预置过期行、Task 13 的 `test_meta_freshness_reports_last_collection(client, session)` 显式同时要两个 fixture。放错目录会让这两个任务在开工当天就因 fixture not found 停摆。`tests/db/` 下**不再**另建 conftest。

**测试库命名（R6 裁定）：** 环境变量统一用 `DATABASE_URL`，值为 `postgresql+asyncpg://postgres:test@localhost:5433/postgres`；`TEST_DATABASE_URL` 只是文档中的别名说法，实现时**只认 `DATABASE_URL`** —— 两个名字并存容易让实现者把测试连到别的库。

- [ ] **Step 1: 写 `docker-compose.test.yml` 与失败测试**

compose 文件定义 `postgres:16-alpine` 服务，端口 `5433:5432`，环境变量 `POSTGRES_PASSWORD=test`，健康检查用 `pg_isready`。

`tests/db/test_dim_models.py`：

```python
async def test_locations_seed_roundtrips(session):
    loc = Location(id=32000000, name="Global", is_country=False)
    session.add(loc)
    await session.commit()
    loaded = await session.get(Location, 32000000)
    assert loaded.name == "Global"
    assert loaded.is_country is False
```

- [ ] **Step 2: 启动测试库并确认测试失败**

```bash
docker compose -f docker-compose.test.yml up -d
pytest tests/db/test_dim_models.py -v
```
Expected: FAIL —— 表不存在或模块不存在

- [ ] **Step 3: 实现 `base.py`、`session.py`、`models.py`**

`models.py` 五个类逐字段对齐规格 §5.1。`Season` 主键为复合 `(league_id, id)`，`id` 字段名为字符串型（如 `'2024-01'`），注意该列名为 `id` 而非 Python 内置冲突。

**`users` 与 `user_clan_subscriptions`（规格 §5.5）不放在本任务**（R10 裁定）：本迁移名为 `0001_dimension_tables`，而用户表不是维表；更重要的是 Task 6 的 Interfaces 已声明这两张表归它建。若此处也建，两处会重复建表并互相冲突。它们由 Task 6 创建、并以其唯一约束测试锁住不变量，本任务只建五张维表。

- [ ] **Step 4: 配置 Alembic 并生成首个迁移**

`migrations/env.py` 从 `Settings` 读 URL，target_metadata 指向 `Base.metadata`。迁移文件必须命名为 `0001_dimension_tables`，`downgrade()` 中 `drop_all()` 表。

- [ ] **Step 5: 运行迁移与测试**

```bash
alembic upgrade head
pytest tests/db/ -v
```
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add docker-compose.test.yml alembic.ini migrations/ app/db/ tests/db/
git commit -m "feat: 数据库基座与五张维表"
```

---

### Task 4: CocClient —— 限流、退避重试、协议校验

**Files:**
- Create: `app/coc/client.py`
- Test: `tests/coc/test_client.py`
- Test: `tests/fixtures/`（Task 5 填充样本）

**Interfaces:**
- Consumes: `Settings.coc_api_token`、`Settings.coc_timeout`、`MemoryRateLimiter`、`app.coc.errors` 全部异常类
- Produces:
  - `class CocClient`：`__init__(self, token: str, rate_limiter: RateLimiter, timeout: float = 15.0, transport: httpx.AsyncBaseTransport | None = None)`
  - `async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]`
  - `async def post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any]`
  - `async def aclose(self) -> None`
  - 状态码映射常量：`STATUS_MAP: dict[int, type[CocError]]`

- [ ] **Step 1: 写失败测试**

`tests/coc/test_client.py`，全部用 `httpx.MockTransport`：

```python
async def test_429_triggers_retry_then_succeeds():
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, json={"reason": "requestThrottled", "message": ""})
        return httpx.Response(200, json={"tag": "#2PP"})
    client = CocClient("t", MemoryRateLimiter(rate=100), transport=httpx.MockTransport(handler))
    assert await client.get("/clans/%232PP") == {"tag": "#2PP"}
    assert len(calls) == 2
```

其余必测用例：
- `test_403_access_denied_raises_without_retry` —— handler 恒返回 403 `{"reason":"accessDenied.invalidIp"}`，断言抛 `CocAccessDenied` 且 handler 只被调用 1 次（验证不重试）
- `test_404_raises_business_error_without_retry` —— 抛 `ClanNotFound`，调用次数 1
- `test_exhausted_retries_raises_throttled` —— 恒返回 429，调用次数为 1 + 3 = 4，抛 `CocThrottled`
- `test_timeout_is_retried_then_raises_coc_timeout` —— handler 抛 `httpx.ReadTimeout`，调用次数 4，抛 `CocTimeout`
- `test_500_maps_to_upstream_error` —— 抛 `CocUpstreamError`
- `test_non_json_body_raises_protocol_error` —— 返回 `text/plain` 的 200，抛 `CocProtocolError`

退避注入：`_sleep` 属性默认 `asyncio.sleep`，测试中替换为记录调用的假函数以断言退避序列 `[1.0, 2.0, 4.0]`。在 `Interfaces` 中明确：`CocClient._sleep: Callable[[float], Awaitable[None]]`，测试需 monkeypatch 此属性。

**注意测试里的 `MemoryRateLimiter(rate=100)` 是有意放宽（R7 裁定），不是违反 Global Constraints 的 8 req/s** —— 那条约束约束的是生产对官方的行为；测试若真按 8 req/s 限速，7 个用例会退化成故意等待。8 与 100 之外还有 Task 3/9 的 DB 测试，同样不适用该约束。评审时请勿判为违规。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/coc/test_client.py -v`
Expected: FAIL —— `ImportError: cannot import name 'CocClient'`

- [ ] **Step 3: 实现 `CocClient`**

要点：
- 内部持一个 `httpx.AsyncClient`，构造时传入 `transport`（测试注入点）与 `timeout`
- 单一 `Authorization: Bearer {token}` 头由 client 统一附加
- 重试循环：最多 3 次重试（即最多 4 次请求），每次失败后 `await self._sleep(2 ** attempt)`，`attempt` 从 0 到 2 对应 1s/2s/4s
- 状态码分派：`STATUS_MAP = {400: CocBusinessError, 403: CocAccessDenied, 404: ClanNotFound, 429: CocThrottled, 500: CocUpstreamError, 503: CocUpstreamError, 504: CocUpstreamError}`。404 需按响应体的 `reason` 细分为 `ClanNotFound` / `PlayerNotFound` / `NotInWar`（读取 `reason` 字段，`notInWar` → `NotInWar`，其余 → `ClanNotFound`）
- 业务态异常（`CocBusinessError`）必须直接抛出、跳过重试循环

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/coc/test_client.py -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add app/coc/client.py tests/coc/test_client.py
git commit -m "feat: CocClient 含令牌桶限流与指数退避重试"
```

---

### Task 5: 官方接口封装与真实响应样本

**Files:**
- Create: `app/coc/tags.py`
- Create: `app/coc/endpoints.py`
- Test: `tests/coc/test_tags.py`
- Create: `tests/fixtures/clan_detail.json`
- Create: `tests/fixtures/player_profile.json`
- Create: `tests/fixtures/locations.json`
- Create: `tests/fixtures/ranking_clans.json`
- Test: `tests/coc/test_endpoints.py`

**Interfaces:**
- Consumes: `CocClient.get` / `CocClient.post`
- Produces:
  - `app/coc/tags.py`：`def normalize_tag(tag: str) -> str`（去空白、去前导 `#`、大写，返回 `#2PP` 形式）；`def quote_tag(tag: str) -> str`（在 `normalize_tag` 基础上编码为 `%232PP`）。**Task 5 建立，Task 7 与 Task 11 复用，实现只此一处。**
  - `app/coc/endpoints.py` 中 30 个 async 函数，每个签名形如 `async def get_clan(client: CocClient, tag: str) -> dict[str, Any]`，返回官方原始 dict：`search_clans`、`get_clan`、`get_clan_members`、`get_clan_warlog`、`get_clan_currentwar`、`get_clan_currentwar_leaguegroup`、`get_clanwarleague_war`、`get_clan_capitalraidseasons`、`get_player`、`verify_player_token`、`get_leaguetiers`、`get_leaguetier`、`get_warleagues`、`get_warleague`、`get_capitalleagues`、`get_capitalleague`、`get_builderbaseleagues`、`get_builderbaseleague`、`get_league_seasons`、`get_league_season_players`、`get_locations`、`get_location`、`get_clan_rankings`、`get_player_rankings`、`get_clan_rankings_builder_base`、`get_player_rankings_builder_base`、`get_capital_rankings`、`get_clan_labels`、`get_player_labels`、`get_current_goldpass_season`

- [ ] **Step 1: 写失败测试**

`tests/coc/test_endpoints.py` 用 `MockTransport` 捕获 `request.url.path`，逐个断言路径正确。**重点覆盖 Review Focus 第 1 条**：

```python
async def test_get_clan_url_encodes_hash():
    seen = []
    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={})
    client = CocClient("t", MemoryRateLimiter(rate=100), transport=httpx.MockTransport(handler))
    await get_clan(client, "2PP")
    assert seen[0].endswith("/clans/%232PP")
```

```python
async def test_tag_is_uppercased_before_request():
    # 输入 "2pp" → 请求路径含 %232PP
```

其余：断言 `get_player(client, "9QJ8L0")` 路径为 `/players/%239QJ8L0`；断言 `get_clan_rankings(client, 32000001, limit=50)` 的 path 为 `/locations/32000001/rankings/clans`、query 中 `limit=50`；断言 `verify_player_token` 使用 POST 且 body 为 `{"token": "..."}`。

`tests/coc/test_tags.py` 独立测归一化函数本身：

```python
def test_normalize_tag_uppercases_and_adds_hash():
    assert normalize_tag("2pp") == "#2PP"
    assert normalize_tag(" #2pp ") == "#2PP"
    assert normalize_tag("#2PP") == "#2PP"

def test_quote_tag_encodes_hash():
    assert quote_tag("2pp") == "%232PP"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/coc/test_tags.py tests/coc/test_endpoints.py -v`
Expected: FAIL —— `ImportError`

- [ ] **Step 3: 实现 `tags.py`**

这是 Review Focus 第 1 条的**唯一实现点**，Task 7 与 Task 11 必须复用，不得各写一份：

```python
def normalize_tag(tag: str) -> str:
    return "#" + tag.strip().lstrip("#").upper()

def quote_tag(tag: str) -> str:
    return quote(normalize_tag(tag), safe="")
```

- [ ] **Step 4: 实现 `endpoints.py`**

每函数签名形如 `async def get_clan(client: CocClient, tag: str) -> dict[str, Any]`。**凡涉及 tag 的路径一律调 `quote_tag`，不得自行拼接。** 例：`get_clan` → `client.get(f"/clans/{quote_tag(tag)}")`。

- [ ] **Step 4: 填入真实响应样本**

从 `https://api.clashofclans.com/v1/clans/%232PP`（需你自己的 Token）抓取一份真实响应，剔除无意义字段后存为 `tests/fixtures/clan_detail.json`；players、locations、rankings/clans 同理。若暂无 Token，可从规格文档 §9 的响应示例手工构造，但须在文件旁注明来源。

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/coc/test_tags.py tests/coc/test_endpoints.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add app/coc/tags.py app/coc/endpoints.py tests/coc/ tests/fixtures/
git commit -m "feat: 标签归一化工具、30 个官方接口封装与真实响应样本"
```

---

### Task 6: 实体表迁移

**Files:**
- Create: `migrations/versions/0002_entity_tables.py`
- Modify: `app/db/models.py`
- Test: `tests/db/test_entity_models.py`

**Interfaces:**
- Consumes: Task 3 的 `Base`
- Produces ORM 类：
  - `Clan`、`ClanCapital`、`ClanMember`、`Player` —— 字段严格对齐规格 §5.2
  - `ClanMember` 与 `Clan` 之间建 FK `clan_tag → clans.tag` 且 `ondelete="CASCADE"`；`ClanMember` 额外建 `player_tag` 索引（供反查玩家所属部落）
  - `clans.location_id` 与 `clan_members.league_tier_id` **只建索引不建 FK**（规格 §5.6）
  - `User`、`UserClanSubscription` —— 规格 §5.5 预留表，本任务建好但无任何逻辑使用
  - 所有表带 `fetched_at: Mapped[datetime]`

- [ ] **Step 1: 写失败测试**

```python
async def test_user_openid_is_unique(session):
    session.add(User(openid="o1", created_at=_now()))
    await session.commit()
    session.add(User(openid="o1", created_at=_now()))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

async def test_user_clan_subscription_is_unique_per_pair(session):
    # 同一 (user_id, clan_tag) 插入两次 → IntegrityError
```

```python
async def test_clan_member_cascade_delete(session):
    clan = Clan(tag="#2PP", name="示例", member_count=1, fetched_at=_now())
    session.add(clan)
    session.add(ClanMember(clan_tag="#2PP", player_tag="#9QJ8L0", role="leader",
                            exp_level=200, fetched_at=_now()))
    await session.commit()
    await session.execute(delete(ClanMember).where(ClanMember.clan_tag == "#2PP"))
    await session.commit()
    # 断言删除成员不报错，且 Player 表无孤儿
```

另测：`test_clan_allows_none_location_id`（`location_id=None` 插入成功，验证无 FK 约束）。

- [ ] **Step 2: 运行测试确认失败**

Run: `alembic upgrade head && pytest tests/db/test_entity_models.py -v`
Expected: FAIL —— 表不存在

- [ ] **Step 3: 实现模型并生成迁移**

用 `Mapped[...]` / `mapped_column(...)` 显式标注全部列。JSONB 字段用 `postgresql.JSONB`：`Clan.badge_urls`、`Clan.labels`、`ClanCapital.districts`、`ClanMember.player_house`、`Player.achievements`、`Player.labels`、`Player.legend_statistics`。

- [ ] **Step 4: 运行迁移与测试**

Run: `alembic upgrade head && pytest tests/db/ -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/db/models.py migrations/versions/0002_entity_tables.py tests/db/
git commit -m "feat: 部落与玩家实体表"
```

---

### Task 7: 官方响应 → ORM 映射器

**Files:**
- Create: `app/coc/mappers.py`
- Test: `tests/coc/test_mappers.py`

**Interfaces:**
- Consumes: `app.db.models` 的 `Clan` / `ClanMember` / `Player` / `ClanCapital` / `Location`；`app.coc.tags.normalize_tag`
- Produces:
  - `def map_clan(data: dict[str, Any], now: datetime) -> Clan`
  - `def map_clan_capital(clan_tag: str, data: dict[str, Any], now: datetime) -> ClanCapital | None`（`data.get("clanCapital")` 为 `None` 时返回 `None`，不得抛异常）
  - `def map_clan_members(clan_tag: str, data: dict[str, Any], now: datetime) -> list[ClanMember]`（读 `data["items"]`）
  - `def map_player(data: dict[str, Any], now: datetime) -> Player`
  - `def map_locations(items: list[dict[str, Any]], now: datetime) -> list[Location]`
  - `def _enum(value: str | None, allowed: set[str], default: str) -> str`

`now` 一律由调用方传入（带时区的 UTC `datetime`），mapper 内部**绝不**调用 `datetime.now()` —— 这让 TTL 判定可测，并为 Review Focus 第 2 条（时区）提供统一的正确性入口。

- [ ] **Step 1: 写失败测试**

```python
def test_map_clan_handles_unknown_extra_fields():
    data = {"tag": "#2PP", "name": "示例", "clanLevel": 15,
            "brandNewFieldAppearingTomorrow": {"x": 1}}
    clan = map_clan(data)
    assert clan.tag == "#2PP"
```

```python
def test_map_player_handles_missing_role_when_no_clan():
    data = {**json.loads(Path("tests/fixtures/player_profile.json").read_text(encoding="utf-8"))}
    data.pop("role", None)
    data.pop("clan", None)
    player = map_player(data)
    assert player.role is None
```

```python
def test_map_clan_normalizes_tag_case():
    assert map_clan({"tag": "#2pp", "name": "x"}).tag == "#2PP"
```

```python
def test_map_clan_falls_back_on_unknown_war_frequency():
    assert map_clan({"tag": "#2PP", "warFrequency": "sometimes"}, now=NOW).war_frequency == "always"

def test_map_clan_capital_returns_none_when_absent():
    # 搜索接口的响应不含 clanCapital 字段 —— 不得抛 KeyError
    assert map_clan_capital("#2PP", {}, now=NOW) is None

def test_map_clan_capital_parses_districts():
    result = map_clan_capital("#2PP", {"capitalHallLevel": 10,
                                      "districts": [{"id": 70000000, "name": "Capital Peak",
                                                     "districtHallLevel": 10}]}, now=NOW)
    assert result.capital_hall_level == 10
    assert result.districts[0]["name"] == "Capital Peak"

def test_map_clan_uses_injected_now_with_timezone():
    # 断言 fetched_at 精确等于传入值，且 tzinfo 不为 None
    tz_aware = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    assert map_clan({"tag": "#2PP"}, now=tz_aware).fetched_at == tz_aware
```

最后一个测试锁住 Review Focus 第 2 条：`fetched_at` 必须是带时区的 UTC，不能是 naive。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/coc/test_mappers.py -v`
Expected: FAIL —— `ImportError`

- [ ] **Step 3: 实现 `mappers.py`**

铁律，三条不可违背：

1. **所有读取一律用 `data.get(key)`，禁止 `data[key]`**；嵌套对象用 `data.get("location") or {}`。
2. 枚举字段经 `_enum` 归一，未知值落 default：`war_frequency` 默认 `always`，`type` 默认 `open`，`role` 默认 `member`，`village` 默认 `home`。
3. tag 归一化调 `app.coc.tags.normalize_tag`（Task 5 提供），**不得自行 strip/upper**。

`now` 从签名传入，仅赋给 `fetched_at`。**禁止在 mapper 内出现 `datetime.now()`。**

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/coc/test_mappers.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/coc/mappers.py tests/coc/test_mappers.py
git commit -m "feat: 官方响应到 ORM 的容错映射器"
```

---

### Task 8: 读时旁路缓存层

**Files:**
- Create: `app/cache/__init__.py`
- Create: `app/cache/ttl.py`
- Create: `app/cache/readthrough.py`
- Test: `tests/cache/test_ttl.py`
- Test: `tests/cache/test_readthrough.py`

**Interfaces:**
- Consumes: `app.coc.errors` 全部异常类；`app.db.session.get_session`
- Produces:
  - `app/cache/ttl.py`：`TTL: dict[str, int]` 常量表；`def get_ttl(resource: str) -> int`；资源键 `"clan"`、`"clan_members"`、`"currentwar"`、`"warlog"`、`"cwl"`、`"player"`、`"leaguetiers"`、`"locations"`、`"labels"`、`"leagues"`、`"rankings"`、`"seasons"`、`"goldpass"`
  - `app/cache/readthrough.py`：
    - `@dataclass class CacheStatus(str, Enum)`：`HIT="HIT"`、`MISS="MISS"`、`STALE="STALE"` —— **枚举值必须大写**，与规格 §6.1 统一响应体 `"cache": "HIT | MISS | STALE"` 及 §3 数据流 `meta.cache=HIT` 逐字一致；前端直接读此值，改大小写即为破坏契约
    - `@dataclass class ReadThroughResult[T]`：`data: T`、`status: CacheStatus`、`fetched_at: datetime | None`、`age_seconds: int | None`
    - `async def read_through(resource: str, key: str, loader: Callable[[], Awaitable[T]], persister: Callable[[T], Awaitable[None]], fetcher: Callable[[], Awaitable[T]], session: AsyncSession) -> ReadThroughResult[T]` —— Python 3.12 支持 PEP 695 泛型语法

- [ ] **Step 1: 写失败测试**

`tests/cache/test_ttl.py`：断言 `get_ttl("currentwar") == 120`、`get_ttl("clan") == 300`、`get_ttl("clan_warlog") == 600`、`get_ttl("locations") == 86400`、`get_ttl("rankings") == 21600`；未知资源抛 `KeyError`。

`tests/cache/test_readthrough.py` 四个核心用例：

```python
async def test_returns_hit_when_row_is_fresh(session):
    # 预置 fetched_at = now - 10s 的 Clan，TTL 300s
    result = await read_through("clan", "#2PP", loader, persister, fetcher, session)
    assert result.status is CacheStatus.HIT
    assert fetcher_called is False
```

```python
async def test_fetches_and_persists_on_miss(session):
    # loader 返回 None → 触发 fetcher → 断言 fetcher 被调用、结果 MISS
```

```python
async def test_degrades_to_stale_when_fetcher_raises_fault(session):
    # loader 返回过期行；fetcher 抛 CocUpstreamError
    # 断言 status is STALE 且 data 仍为旧值
```

```python
async def test_does_not_degrade_business_error_to_stale(session):
    # loader 返回过期行；fetcher 抛 ClanNotFound
    # 断言 pytest.raises(ClanNotFound) —— 业务错误必须冒泡，不得返回陈旧数据
```

本任务最重要的三个断言：

- **`does_not_degrade_business_error_to_stale`** —— 业务错误不降级。若实现错误地把它降级为 STALE，用户会看到一个明显不存在的部落还带着旧数据。
- **`stale_when_all_upstream_fails_is_the_ip_or_token_fault_path`** —— 用 `CocAccessDenied` 而非常规故障，模拟「Token 过期 / 公网 IP 变更」这个**生产环境最可能发生的故障**。此时期望逐条降级为 STALE 而非让用户看到 502。这是 Review Focus 第 3 条的落点。
- **`age_seconds_uses_tz_aware_arithmetic`** —— `fetched_at` 与 `now` 都必须 tz-aware，混用会抛 `TypeError: can't subtract offset-naive and offset-aware datetimes`。这是 Review Focus 第 2 条在缓存层的落点。

```python
async def test_stale_when_all_upstream_fails_is_the_ip_or_token_fault_path(session):
    # loader 返回过期行；fetcher 抛 CocAccessDenied(reason="accessDenied.invalidIp")
    result = await read_through("clan", "#2PP", loader, persister,
                               raising(CocAccessDenied), session)
    assert result.status is CacheStatus.STALE

async def test_no_stale_when_row_is_absent(session):
    # 首次部署 + IP 未进白名单就是这个场景：库里没有旧数据可退
    # 断言异常向上冒泡，不得伪造一个 STALE 空结果
    with pytest.raises(CocAccessDenied):
        await read_through("clan", "#2PP", empty_loader, persister,
                           raising(CocAccessDenied), session)

async def test_age_seconds_uses_tz_aware_arithmetic(session):
    # 预置 fetched_at = UTC now - 60s，断言 55 <= age_seconds <= 65
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/cache/ -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.cache'`

- [ ] **Step 3: 实现 `ttl.py` 与 `readthrough.py`**

`read_through` 的分支判定顺序严格为：

1. loader 取行 → 若有行且未过期 → 返回 `HIT`
2. 否则调 fetcher → 成功 → persister → 返回 `MISS`
3. 若 `isinstance(exc, CocBusinessError)` → **无条件重抛**（业务态不是故障，不能用陈旧数据掩盖）
4. 若 `isinstance(exc, (CocFaultError, CocAccessDenied))` → 有旧行返回 `STALE`，无旧行重抛

**`CocAccessDenied` 属于可降级类**，这是本任务的关键设计：它代表 Token 过期或公网 IP 变更，会导致官方调用**全线**失败；若此时一律重抛，用户面对的是一片 502。降级为 STALE 让已有缓存继续服务用户，而「告警」是正交的观测关注点，由 `app/api/errors.py` 记录日志与告警负责，**不**通过禁止降级来实现。（注意 Task 2 中 `CocAccessDenied` 不是 `CocFaultError` 的子类 —— 那是为了禁止自动重试；此处必须显式并列。）

过期判定：`row is not None and row.fetched_at + timedelta(seconds=ttl) > now`。**`now` 用 `datetime.now(UTC)`，必须是带时区的 UTC**（Review Focus 第 2 条）。`age_seconds` 用 `(now - row.fetched_at).total_seconds()` 计算，两个操作数都须 tz-aware。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/cache/ -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/cache/ tests/cache/
git commit -m "feat: 读时旁路缓存与 TTL 表"
```

---

### Task 9: 查询 API —— 部落与玩家

**Files:**
- Create: `app/api/deps.py`
- Create: `app/api/schemas.py`
- Create: `app/api/errors.py`
- Create: `app/api/routes/clans.py`
- Create: `app/api/routes/players.py`
- Test: `tests/api/test_clans.py`
- Test: `tests/api/test_players.py`

**Interfaces:**
- Consumes: `read_through`、`app.coc.endpoints` 全部函数、`app.coc.mappers`
- Produces:
  - `app/api/schemas.py`：`MetaOut(cache: str, fetched_at: datetime | None, age_seconds: int | None, ttl_seconds: int)`、`DataOut[T](data: T, meta: MetaOut)`、`ErrorBody(code: str, message: str, upstream_reason: str | None)`、`ErrorOut(error: ErrorBody)`、常量 **`MAX_PAGE_SIZE = 50`** 与 **`DEFAULT_PAGE_SIZE = 20`**、函数 `def clamp_page_size(page_size: int) -> int`（返回 `min(page_size, MAX_PAGE_SIZE)`）。**Task 13、16、17 一律复用此三者，不得各自定义上限。**
  - `app/api/errors.py`：`ERROR_CODE_MAP: dict[str, tuple[int, str]]` 把 `CocError` 子类映射到 HTTP 码与对外 code；`def coc_error_handler(request, exc) -> JSONResponse`
  - `app/api/deps.py`：`async def get_coc_client() -> AsyncGenerator[CocClient, None]`（lifespan 内建单例并 yield）
  - 路由：`GET /api/v1/clans/{tag}`、`GET /api/v1/clans/{tag}/members`、`GET /api/v1/clans/search`、`GET /api/v1/players/{tag}`、`POST /api/v1/players/{tag}/verifytoken`

- [ ] **Step 1: 写失败测试**

`tests/api/test_clans.py`：

```python
async def test_get_clan_returns_200_with_meta(client, monkeypatch):
    monkeypatch.setattr(coc, "get_clan", fake_returning_fixture)
    resp = await client.get("/api/v1/clans/%232PP")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["tag"] == "#2PP"
    assert body["meta"]["cache"] in {"HIT", "MISS", "STALE"}
```

```python
async def test_get_clan_lowercase_tag_resolves(client, monkeypatch):
    resp = await client.get("/api/v1/clans/2pp")
    assert resp.status_code == 200
```

```python
async def test_invalid_tag_returns_400(client):
    resp = await client.get("/api/v1/clans/not-a-tag")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_TAG"
```

```python
async def test_clan_not_found_returns_404(client, monkeypatch):
    monkeypatch.setattr(coc, "get_clan", raises(ClanNotFound))
    resp = await client.get("/api/v1/clans/%23ZZZZ")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CLAN_NOT_FOUND"
```

```python
async def test_stale_fallback_returns_200_not_502(client, monkeypatch):
    # 预置过期行 + fetcher 抛 CocUpstreamError
    resp = await client.get("/api/v1/clans/%232PP")
    assert resp.status_code == 200
    assert resp.json()["meta"]["cache"] == "STALE"
```

前面两个测试覆盖 Review Focus 第 3 条：即使官方全线 403/5xx，已有缓存的用户拿到的仍是 200 + stale，而不是一片报错。紧接着的第三个测恰恰相反 —— **首次部署时库里没有旧数据可退**，此时必须诚实地返回 502，不能伪造成功。

```python
async def test_stale_is_not_used_when_no_prior_data_exists(client, monkeypatch):
    # 库中该 tag 完全没有行 + fetcher 抛 CocAccessDenied
    # 断言 502，error.code == "UPSTREAM_UNAVAILABLE"
    resp = await client.get("/api/v1/clans/%23FRESH")
    assert resp.status_code == 502
```

```python
async def test_page_size_above_50_is_capped_not_passed_to_upstream(client, monkeypatch):
    # Review Focus 第 4 条
    captured = {}
    monkeypatch.setattr(coc, "get_clan_members", capture_returning([], captured))
    resp = await client.get("/api/v1/clans/%232PP/members?page_size=500")
    assert resp.status_code == 200
    assert captured["limit"] == 50          # 透传给官方则会拿到 badRequest
```

```python
async def test_clan_members_beyond_first_page_returns_empty_list(client):
    # Review Focus 第 4 条：越界页返回空列表，不是 404 也不是 500
    resp = await client.get("/api/v1/clans/%232PP/members?page=999")
    assert resp.status_code == 200
    assert resp.json()["data"] == []
```

`tests/api/test_players.py` 补齐玩家侧，含规格 §6.4 中尚未覆盖的 verifytoken：

```python
async def test_get_player_returns_200(client, monkeypatch): ...
async def test_verify_player_token_returns_200_with_status(client, monkeypatch):
    monkeypatch.setattr(coc, "verify_player_token", fake_returning({"tag": "#9QJ8L0",
                                                                    "token": "t",
                                                                    "status": "ok"}))
    resp = await client.post("/api/v1/players/%239QJ8L0/verifytoken",
                       json={"token": "t"})
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ok"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/api/test_clans.py -v`
Expected: FAIL —— 路由不存在返回 404

- [ ] **Step 3: 实现统一响应与错误处理**

`ERROR_CODE_MAP` 精确取值（规格 §6.2）：
```python
{
  ClanNotFound: (404, "CLAN_NOT_FOUND"),
  PlayerNotFound: (404, "PLAYER_NOT_FOUND"),
  NotInWar: (404, "CLAN_NOT_IN_WAR"),
  WarLogPrivate: (403, "WARLOG_PRIVATE"),
  CocThrottled: (502, "UPSTREAM_THROTTLED"),
  CocUpstreamError: (502, "UPSTREAM_UNAVAILABLE"),
  CocTimeout: (502, "UPSTREAM_UNAVAILABLE"),
  CocAccessDenied: (502, "UPSTREAM_UNAVAILABLE"),
  CocProtocolError: (502, "UPSTREAM_UNAVAILABLE"),
}
```

在 `create_app()` 中 `app.add_exception_handler(CocError, coc_error_handler)`。注意 `upstream_reason` 字段填 `exc.reason`。

**`CocAccessDenied → 502` 与 Task 8 的「可降级为 STALE」不矛盾**：`read_through` 在**库里有旧数据时**已经降级为 STALE 并返回 200，根本不会抛到本 handler；只有**首次部署、库里一行都没有**时异常才会穿透上来，此时返回 502 是诚实的。本 handler 同时负责写 warning 日志（含 `exc.reason`），供 §7.4 的告警规则消费 —— 告警不靠「禁止降级」来实现。

- [ ] **Step 4: 实现路由**

**分页必须截断而非拒绝**（这是 Review Focus 第 4 条的关键，也最容易做错）：

```python
page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1)
# handler 内：effective_limit = clamp_page_size(page_size)
```

**不要**用 `le=50` —— 那会让 `?page_size=500` 返回 422，而设计意图是**截断到 50 并返回 200**（官方 API 只接受 1–50，透传会得到 `badRequest`；让调用方因一个可自动修正的参数吃 422 不合理）。`ge=1` 仍保留，因为负数没有可解释的归一化目标。

`clamp_page_size` 是全项目唯一的截断点，Task 13 / 16 / 17 的分页路由都调它 —— 若发现某处手写了 `min(page_size, 50)`，即为实现偏离本计划。

路径参数 `tag: str` 同理：非法值走 400 `INVALID_TAG` 而非 422，在 handler 中捕获 `RequestValidationError` 并转换。

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/api/ -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add app/api/ tests/api/
git commit -m "feat: 部落与玩家查询 API 及统一错误响应"
```

---

### Task 10: 战场表迁移与战报 API

**Files:**
- Create: `migrations/versions/0003_war_tables.py`
- Modify: `app/db/models.py`
- Create: `app/coc/mappers.py`（追加 war mapper）
- Create: `app/api/routes/clans.py`（追加三个路由）
- Test: `tests/db/test_war_models.py`
- Test: `tests/api/test_warlog.py`

**Interfaces:**
- Consumes: Task 9 的 `read_through` 与响应封装
- Produces ORM：`ClanWar`(PK `clan_tag`)、`ClanWarLog`(自增 `id`，`UNIQUE(clan_tag, end_time, result)`)、`CwlLeagueGroup`(PK `clan_tag`)、`CwlWar`(PK `war_tag`)、`CapitalRaidSeason`(PK `id`)、`CapitalRaidClan`(复合 PK，`season_id` FK CASCADE)。新增 mapper：`map_clan_war`、`map_war_logs`（返回 `(clan_tag, list[ClanWarLog])`）、`map_cwl_group`。新增路由：`GET /api/v1/clans/{tag}/warlog`、`GET /api/v1/clans/{tag}/currentwar`、`GET /api/v1/clans/{tag}/cwl`。

- [ ] **Step 1: 写失败测试**

```python
async def test_war_log_unique_constraint_prevents_duplicates(session):
    # 同一 (clan_tag, end_time, result) 插入两条 → 第二次抛 IntegrityError
```

```python
async def test_warlog_private_returns_403(client, monkeypatch):
    monkeypatch.setattr(coc, "get_clan_warlog", raises(WarLogPrivate))
    resp = await client.get("/api/v1/clans/%232PP/warlog")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "WARLOG_PRIVATE"
```

```python
async def test_currentwar_not_in_war_returns_404_business_code(client, monkeypatch):
    monkeypatch.setattr(coc, "get_clan_currentwar", raises(NotInWar))
    resp = await client.get("/api/v1/clans/%232PP/currentwar")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CLAN_NOT_IN_WAR"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `alembic upgrade head && pytest tests/db/test_war_models.py tests/api/test_warlog.py -v`
Expected: FAIL

- [ ] **Step 3: 实现模型、迁移与 mapper**

`ClanWar` 只存单边视角（`current_score` / `total_score` / `attack` / `defense` / `opponent` 均为 JSONB）。`ClanWarLog.end_time` 为 `TIMESTAMPTZ`，唯一约束 `(clan_tag, end_time, result)`。

- [ ] **Step 4: 实现路由**

warlog 的 TTL 用 `"clan_warlog"`（600s）。currentwar 用 `"currentwar"`（120s）。**业务错误（`WarLogPrivate`、`NotInWar`）不得走 STALE 降级** —— 由 Task 8 的 `read_through` 已保证，此处只需确保路由不额外 try/except。

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/db/ tests/api/ -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add app/db/models.py app/coc/mappers.py app/api/routes/clans.py migrations/versions/0003_war_tables.py tests/
git commit -m "feat: 部落战战报、当前战与 CWL 接口"
```

---

### Task 11: 排行榜统一表与全量替换刷新

**Files:**
- Create: `migrations/versions/0004_rankings.py`
- Modify: `app/db/models.py`
- Create: `app/collector/__init__.py`
- Create: `app/collector/rankings_service.py`
- Test: `tests/db/test_rankings_refresh.py`

**Interfaces:**
- Consumes: `Location`（Task 3）
- Produces:
  - ORM `Ranking`，全部列与规格 §5.4 一致；`UNIQUE(kind, location_id, league_id, season_id, tag)`；索引 `(kind, location_id, rank)` 与 `(kind, league_id, season_id, rank)`
  - `RankingKind` StrEnum：`clans`、`players`、`capitals`、`clans_builder_base`、`players_builder_base`、`season_players`
  - `app/collector/rankings_service.py`：`async def replace_rankings(session: AsyncSession, kind: RankingKind, location_id: int | None, league_id: int | None, season_id: str | None, items: list[dict[str, Any]]) -> int` —— 返回写入条数

- [ ] **Step 1: 写失败测试**

**本任务最关键的测试**，它锁住规格 §5.4 的核心设计意图：

```python
async def test_replace_rankings_removes_entries_that_dropped_off_the_board(session):
    await replace_rankings(session, RankingKind.clans, 32000001, None, None,
                           [{"tag": "#AAA", "name": "A", "rank": 1},
                            {"tag": "#BBB", "name": "B", "rank": 2}])
    await replace_rankings(session, RankingKind.clans, 32000001, None, None,
                           [{"tag": "#AAA", "name": "A", "rank": 1}])
    tags = (await session.execute(
        select(Ranking.tag).where(Ranking.kind == RankingKind.clans,
                                  Ranking.location_id == 32000001))).scalars().all()
    assert tags == ["#AAA"]
```

```python
async def test_replace_rankings_does_not_touch_other_scope(session):
    # 写入 location 32000001 与 32000002 两组，再替换前者
    # 断言后者数据完好
```

```python
async def test_replace_rankings_normalizes_tag_case(session):
    await replace_rankings(session, RankingKind.clans, 32000001, None, None,
                           [{"tag": "#aaa", "name": "A", "rank": 1}])
    # 断言存储为 "#AAA"，且重复写入大小写不同的 tag 不会产生两行
```

- [ ] **Step 2: 运行测试确认失败**

Run: `alembic upgrade head && pytest tests/db/test_rankings_refresh.py -v`
Expected: FAIL —— 表不存在

- [ ] **Step 3: 实现模型与迁移**

`Ranking` 的 `location_id`、`league_id`、`season_id` **不建 FK**（规格 §5.6）。`tag` 长度 10，`name` 长度 100。

- [ ] **Step 4: 实现 `replace_rankings`**

单事务内：`DELETE` 该 scope 下全部行 → `session.execute(insert(Ranking), [dict, ...])` 批量插入。tag 归一化**复用 Task 5 的 `app.coc.tags.normalize_tag`**（不新建、不本地实现）。

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/db/test_rankings_refresh.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add app/db/models.py app/collector/rankings_service.py migrations/versions/0004_rankings.py tests/db/
git commit -m "feat: 排行榜统一表与按 scope 全量替换刷新"
```

---

### Task 12: 采集调度器与 collector_runs

**Files:**
- Create: `migrations/versions/0005_collector_runs.py`
- Modify: `app/db/models.py`
- Create: `app/collector/scheduler.py`
- Create: `app/collector/service.py`
- Create: `app/collector/jobs/__init__.py`
- Create: `app/collector/jobs/static_data.py`
- Create: `app/collector/jobs/rankings.py`
- Create: `app/collector/jobs/leagues.py`
- Create: `app/collector/jobs/seasons.py`
- Modify: `app/main.py`
- Test: `tests/collector/test_scheduler.py`
- Test: `tests/collector/test_jobs.py`

**Interfaces:**
- Consumes: `app.config.get_settings()`、`replace_rankings`、`app.coc.endpoints`
- Produces:
  - ORM `CollectorRun`（列见规格 §5.5）
  - `app/collector/scheduler.py`：`def build_scheduler(settings: Settings) -> AsyncIOScheduler`；`SCHEDULE_SPEC: list[tuple[str, str, int]]`
  - `app/collector/service.py`：`async def run_job(job_name: str, settings: Settings, session: AsyncSession) -> str`（返回 status）
  - `app/collector/jobs/static_data.py`：`async def collect_static_data(client, session) -> dict[str, int]`
  - `app/collector/jobs/rankings.py`：`async def collect_rankings(client, session) -> dict[str, int]`
  - `app/collector/jobs/leagues.py`：`async def collect_leagues(client, session) -> dict[str, int]`
  - `app/collector/jobs/seasons.py`：`async def collect_seasons(client, session) -> dict[str, int]` —— 写入 `Season` 表与 `kind = season_players` 的 `rankings` 行，供 Task 13 的 `/rankings/season/{league_id}/{season_id}` 读取
  - `app/main.py` 的 lifespan 按 `settings.app_role` 决定是否 `scheduler.start()`

- [ ] **Step 1: 写失败测试**

`tests/collector/test_scheduler.py`：

```python
def test_role_all_starts_scheduler(settings_all):
    # lifespan 启动后断言 scheduler.running is True
def test_role_api_skips_scheduler(settings_api):
    # 断言 scheduler.running is False
def test_role_collector_skips_http_app(settings_collector):
```

`tests/collector/test_jobs.py`：

```python
async def test_collect_rankings_records_partial_failure(session, monkeypatch):
    # 三个地区，第二个抛 CocUpstreamError
    # 断言 CollectorRun.status == "partial"，items_ok == 2，items_failed == 1，error 非空
```

```python
async def test_collect_static_data_is_idempotent(session, monkeypatch):
    # 连续执行两次，断言 locations 行数不翻倍
```

```python
async def test_collect_seasons_writes_rankings_and_season_rows(session, monkeypatch):
    # mock get_warleagues 返回 [{"id": 48000000, "name": "Crystal League I"}]
    # mock get_league_season_players 返回两条玩家名次
    # 断言 Season 表有对应行，且 rankings 表有 kind=season_players 的两条
```

- [ ] **Step 2: 运行测试确认失败**

Run: `alembic upgrade head && pytest tests/collector/ -v`
Expected: FAIL

- [ ] **Step 3: 实现模型与迁移**

`CollectorRun.status` 为 `String` 而非数据库 ENUM（便于加值而无需迁移）；Python 侧用 `RunStatus` StrEnum 约束。

- [ ] **Step 4: 实现 job 编排**

每个 job 结构相同：`run_job` 先插入 `CollectorRun(status="running", started_at=now)` 并立即 commit（保证崩溃后能看到未完成任务），执行后更新为 success / partial / failed 并写 `finished_at` 与 `error`。

`collect_rankings` 遍历 `select(Location).where(Location.is_country.is_(True))`，对每个地区 × 每种 kind 调用对应 endpoints 函数并 `replace_rankings`。**串行执行，依赖 Task 2 的令牌桶限速**（不在本层再写 sleep）。

`collect_static_data` 采集 `leaguetiers`、`locations`、`labels/clans`、`labels/players`、`goldpass/seasons/current`。

`collect_seasons` 先 `get_warleagues` 取联赛清单，再对每个联赛 `get_league_seasons` 取赛季列表 upsert 到 `Season`，随后对**当前赛季**调 `get_league_season_players` 并 `replace_rankings(kind=season_players, league_id=..., season_id=...)`。历史赛季只存 `Season` 行、**不**抓排名（否则每次触发会扫遍几十年的联赛数据，打爆令牌桶）。

- [ ] **Step 5: 接入 lifespan 并错峰**

`SCHEDULE_SPEC` 的 cron 表达式必须错开整点，避免同一秒向官方发起大量请求：

```python
SCHEDULE_SPEC = [
    ("17 3 * * *",  "static_data", 86400),
    ("13 */6 * * *", "rankings",   21600),
    ("41 * * * *",  "leagues",     3600),
    ("29 * * * *",  "seasons",     3600),
]
```

- [ ] **Step 6: 运行测试确认通过**

Run: `pytest tests/collector/ -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add app/collector/ app/main.py app/db/models.py migrations/versions/0005_collector_runs.py tests/collector/
git commit -m "feat: 采集调度器与任务执行记录"
```

---

### Task 13: 排行榜与地区 API

**Files:**
- Create: `app/api/routes/rankings.py`
- Modify: `app/api/routes/system.py`
- Test: `tests/api/test_rankings.py`

**Interfaces:**
- Consumes: `Ranking`、`RankingKind`、`Location`、`League`、`Season`
- Produces 路由：
  - `GET /api/v1/locations`
  - `GET /api/v1/rankings/clans`、`/players`、`/capitals`、`/clans_builder_base`、`/players_builder_base`（均带 `locationId: int = 32000001` 默认值，对应中国）
  - `GET /api/v1/rankings/season/{league_id}/{season_id}`
  - `GET /api/v1/leagues/{kind}`
  - `GET /api/v1/meta/freshness` → `{"data": {"rankings": {"32000001": "<fetched_at 字符串>"}, ...}}`

- [ ] **Step 1: 写失败测试**

```python
async def test_rankings_clans_defaults_to_china(client):
    resp = await client.get("/api/v1/rankings/clans")
    assert resp.status_code == 200
    assert resp.json()["meta"]["cache"] in {"HIT", "MISS", "STALE"}

async def test_rankings_page_size_is_capped_at_50(client):
    resp = await client.get("/api/v1/rankings/clans?page_size=500")
    assert resp.status_code == 200
    # 断言传给 DB 的 limit 为 50 而非 500 —— 走 Task 9 的 clamp_page_size
```

```python
async def test_meta_freshness_reports_last_collection(client, session):
    resp = await client.get("/api/v1/meta/freshness")
    assert "rankings" in resp.json()["data"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/api/test_rankings.py -v`
Expected: FAIL —— 404

- [ ] **Step 3: 实现路由**

排序固定 `ORDER BY rank ASC`。返回条目含 `rank`、`previous_rank`、`tag`、`name`，以及按 kind 填充对应指标字段（部落类填 `points`/`members`/`clan_level`；玩家类填 `trophies`/`exp_level`/`attack_wins`）。

**这些路由只读库，不触发回源** —— 排行榜由定时任务写入。若库中无该 scope 数据，返回空列表并在 `meta.cache` 标 `"MISS"`，**不**触发 `read_through`（避免 40 个地区 × 6 种榜 × 用户请求把令牌桶打爆）。

分页与 `locationId` 默认值从 Task 9 复用：`page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1)` + `clamp_page_size(page_size)`，`locationId: int = 32000001`（中国）。`page` 越界时返回空列表而非 404（Review Focus 第 4 条）。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/api/ -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/api/routes/rankings.py app/api/routes/system.py tests/api/test_rankings.py
git commit -m "feat: 排行榜、地区与数据新鲜度接口"
```

---

### Task 14: readyz 与对外限流

**Files:**
- Create: `app/middleware.py`
- Modify: `app/api/routes/system.py`
- Modify: `app/main.py`
- Test: `tests/api/test_system_extended.py`
- Test: `tests/api/test_rate_limit.py`

**Interfaces:**
- Consumes: `Settings`、`engine`、`scheduler` 状态
- Produces：
  - `app/middleware.py`：`class RateLimitMiddleware(BaseHTTPMiddleware)`，`__init__(app, requests_per_minute: int = 60)`；`app/api/routes/system.py` 新增 `GET /readyz` → `200 {"status":"ready"}` 或 `503 {"status":"not_ready"}`（DB `SELECT 1` 失败或调度器未运行且 `app_role == "all"` 时返回 503）

- [ ] **Step 1: 写失败测试**

```python
async def test_readyz_returns_503_when_db_unreachable(client, monkeypatch):
    # monkeypatch engine.execute 抛异常
    resp = await client.get("/readyz")
    assert resp.status_code == 503

async def test_rate_limit_blocks_61st_request_in_a_minute(client):
    # 必须打非豁免端点，不能打 /healthz —— 本任务自己豁免了 /healthz
    for _ in range(60):
        assert (await client.get("/api/v1/locations")).status_code == 200
    resp = await client.get("/api/v1/locations")
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "RATE_LIMITED"
```

```python
async def test_rate_limit_does_not_apply_to_healthz(client):
    # /healthz 不计入限流桶，供容器健康检查无限调用
    for _ in range(200):
        assert (await client.get("/healthz")).status_code == 200
```

**这两个测试的端点必须不同（R4 裁定）：** 原文两个测试都打 `/healthz`，而该任务自己规定 `/healthz` 不计入限流桶 —— 字面实现下第一个测试永远拿不到 429。故「第 61 次 429」改用 Task 13 已建好的 `/api/v1/locations`，只有豁免测试继续打 `/healthz`。这两个测试一条不改就会撞死。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/api/test_system_extended.py tests/api/test_rate_limit.py -v`
Expected: FAIL

- [ ] **Step 3: 实现中间件与 readyz**

限流用进程内字典 `dict[str, list[float]]` 记录每个客户端 IP 的请求时间戳；每分钟清理一次过期条目防止内存增长。取 IP 用 `request.client.host`，**在 nginx 反代后需信任 `X-Forwarded-For` 的第一个值**（部署配置里 `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`）。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/api/ -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/middleware.py app/api/routes/system.py app/main.py tests/api/
git commit -m "feat: 就绪探针与对外 IP 限流"
```

---

# Phase A 验收

- [ ] **Step A1**: `pytest` 全绿
- [ ] **Step A2**: `docker compose -f docker-compose.test.yml up -d && alembic upgrade head && pytest` 从空库跑通
- [ ] **Step A3**: 手动冒烟 —— 启动服务，用真实 Token 请求 `/api/v1/clans/%232PP`，验证 `meta.cache` 为 `"MISS"`、二次请求为 `"HIT"`（注意规格 §6.1 为**大写**）
- [ ] **Step A4**: 提交 Phase A 汇总：`git commit -m "feat: Phase A 数据管道与查询能力"`

---

# Phase B · 内容管理 + 后台 + 投稿

### Task 15: 升级数据表迁移与导入 CLI

**Files:**
- Create: `migrations/versions/0006_upgrade_tables.py`
- Modify: `app/db/models.py`
- Create: `app/content/__init__.py`
- Create: `app/content/game_data.py`
- Create: `app/cli.py`
- Create: `tests/fixtures/coc_units_mini.json`
- Test: `tests/content/test_game_data.py`

**Interfaces:**
- Consumes: `Settings`
- Produces:
  - ORM `UpgradeItem`（列见规格 §5.5，`UNIQUE(category, name, village, level)`）、`UpgradeRoute`、`UpgradeRouteStep`（`route_id` FK CASCADE）
  - `app/content/game_data.py`：`async def fetch_units_data(cache_dir: Path | None = None) -> dict[str, Any]`（读 npm registry 元信息 → 下载 tarball → 解压读 `package/dist/util/raw.json` → 返回 `{"RAW_UNITS": [...], "RAW_SUPER_UNITS": [...]}`）；`def units_to_rows(units: list[dict[str, Any]]) -> list[dict[str, Any]]`；`async def import_upgrade_items(session: AsyncSession, rows: list[dict[str, Any]]) -> int`
  - `app/cli.py`：`async def cmd_import_game_data() -> None` —— **只此一个命令**（R3 裁定：原计划还列了 `cmd_create_admin`，已删除，见下方说明）

**调用关系约定**：`cmd_import_game_data` 负责把 `fetch_units_data()` 的结果**拆开**，只把 `data["RAW_UNITS"]` 交给 `units_to_rows`，`data["RAW_SUPER_UNITS"]` 直接丢弃 —— 超级兵种是单次升级（`resourceCost` / `cooldown`），没有 `upgrade.cost` 数组，产生不了等级行。`units_to_rows` 自身不关心来源，因此测试可以直接喂一个单位数组（见下方 fixture）。`units_to_rows` 仍须防御性跳过 `upgrade` 缺失的条目。

- [ ] **Step 1: 写最小 fixture 与失败测试**

`tests/fixtures/coc_units_mini.json` 只放 2 个单位的裁剪版（一个 troop 一个 hero），含 `category`、`village`、`upgrade.cost`、`upgrade.time`、`upgrade.resource`、`unlock`。

`tests/content/test_game_data.py`：

```python
def test_units_to_rows_generates_one_row_per_level():
    units = json.loads(Path("tests/fixtures/coc_units_mini.json").read_text(encoding="utf-8"))
    rows = units_to_rows(units)
    barbarian = [r for r in rows if r["name"] == "Barbarian"]
    assert len(barbarian) == 12          # upgrade.cost 有 12 项
    assert barbarian[0]["level"] == 1     # 索引 0 表示 1 → 2 级
    assert barbarian[0]["elixir"] == 10000
```

```python
def test_units_to_rows_maps_resources_to_columns():
    # resource == "Dark Elixir" → dark_elixir 有值，gold/elixir 为 None
```

```python
def test_units_to_rows_leaves_name_zh_and_builder_count_null():
    assert all(r["name_zh"] is None for r in units_to_rows(units))
    assert all(r["builder_count"] is None for r in units_to_rows(units))
```

```python
async def test_import_is_idempotent(session):
    rows = units_to_rows(units)
    first = await import_upgrade_items(session, rows)
    second = await import_upgrade_items(session, rows)
    assert first == second
    total = (await session.execute(select(func.count()).select_from(UpgradeItem))).scalar_one()
    assert total == first
```

最后一个测试锁住规格 §10.3 第 8 条「幂等：重复执行安全」。

- [ ] **Step 2: 运行测试确认失败**

Run: `alembic upgrade head && pytest tests/content/test_game_data.py -v`
Expected: FAIL

- [ ] **Step 3: 实现模型与迁移**

`UpgradeItem.category` 用 `String` + Python `StrEnum`（`building`/`troop`/`spell`/`hero`/`equipment`）。`gold`/`elixir`/`dark_elixir` 为 `BigInteger | None`。`build_time_seconds` 为 `Integer | None`。

- [ ] **Step 4: 实现 `game_data.py`**

- `fetch_units_data` 全程用 `urllib.request` + `tarfile`，**不得调用 npm 或 Node.js**（规格 §10.3）。registry URL：`https://registry.npmjs.org/clashofclans.js`，tarball URL 从 `versions[latest]["dist"]["tarball"]` 取。`cache_dir` 给出时把 tarball 落盘以便离线重跑。
- `units_to_rows` 遍历入参 `units` 数组中的每个单位，**跳过 `upgrade` 或 `upgrade.cost` 缺失的条目**（超级兵种在 `RAW_SUPER_UNITS` 中，本身不含等级数组，见上方调用关系约定；此处是防御性兜底）。同时只接受 `category` ∈ {troop, spell, hero, equipment}，其余类别既不产生行也不报错。
- 索引映射：`upgrade.cost[i]` 与 `upgrade.time[i]` 生成 `level = i + 1` 的一行（表示从 `level` 升到 `level + 1`）。
- `unlock.hall` → `required_townhall_level`；仅当 `village == "builderBase"` 时 `unlock.buildingLevel` → `required_builder_base_level`，否则置 `None`。
- 资源分列：`upgrade.resource` 取值 `Gold`/`Elixir`/`Dark Elixir`/`Builder Elixir`，分别写入对应列，其余为 `None`。
- `name_zh`、`builder_count`、`notes` 一律 `None`。
- `import_upgrade_items` 用 PostgreSQL `insert(...).on_conflict_do_update(index_elements=["category","name","village","level"], set_=...)`，**返回值恒为 `len(rows)`**（R5 裁定）—— 上方 `test_import_is_idempotent` 断言 `first == second`，只有返回值恒等于输入行数时该断言才是稳定语义；若返回「实际变更行数」，测试就会退化为断言实现细节。行数校验由 `total == first` 那条断言负责。

- [ ] **Step 5: 实现 `cli.py` 与 `main.py` 入口**

`app/cli.py` 顶层加 `main()`，用 `argparse` **只有一个**子命令 `import-game-data`，`python -m app.cli import-game-data` 可运行。

**为何没有 `create-admin` 命令（R3 裁定）：** 原计划在此列了 `create-admin`，但 Task 19 的后台认证明确走环境变量 `ADMIN_USERNAME` / `ADMIN_PASSWORD`，且规格中不存在任何管理员表。保留这个命令等于凭空引入一张表、或制造第二条与后台互不知情的凭据来源 —— 二者都与规格冲突。**管理员账号只在 `.env` 里配置，不入库。**

- [ ] **Step 6: 运行测试确认通过**

Run: `pytest tests/content/ -v`
Expected: PASS

- [ ] **Step 7: 验证真实数据规模**

```bash
python -m app.cli import-game-data
```
Expected: 输出 `troop 599 / spell 111 / hero 513 / equipment 850`，合计 **2073** 行（规格 §10.3）。若数量不符，检查 `RAW_SUPER_UNITS` 是否被正确跳过。

- [ ] **Step 8: 提交**

```bash
git add app/content/ app/cli.py app/db/models.py migrations/versions/0006_upgrade_tables.py tests/content/
git commit -m "feat: 升级数据表与 npm 数据集导入命令"
```

---

### Task 16: 升级数据查询 API

**Files:**
- Create: `app/api/routes/upgrade.py`
- Test: `tests/api/test_upgrade.py`

**Interfaces:**
- Consumes: `UpgradeItem`、`UpgradeRoute`、`UpgradeRouteStep`
- Produces 路由：
  - `GET /api/v1/upgrade/routes?from_th=&to_th=` → `DataOut[list[UpgradeRouteOut]]`
  - `GET /api/v1/upgrade/routes/{id}` → 含 `steps` 数组
  - `GET /api/v1/upgrade/items?category=&village=&name=&page=&page_size=` → `DataOut[list[UpgradeItemOut]]`

- [ ] **Step 1: 写失败测试**

```python
async def test_upgrade_items_filters_by_category(client):
    resp = await client.get("/api/v1/upgrade/items?category=hero")
    assert resp.status_code == 200
    assert all(i["category"] == "hero" for i in resp.json()["data"])

async def test_upgrade_items_empty_table_returns_empty_list_not_error(client):
    resp = await client.get("/api/v1/upgrade/items?category=troop")
    assert resp.status_code == 200
    assert resp.json()["data"] == []

async def test_upgrade_items_rejects_invalid_category(client):
    resp = await client.get("/api/v1/upgrade/items?category=nonexistent")
    assert resp.status_code == 400
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/api/test_upgrade.py -v`
Expected: FAIL —— 404

- [ ] **Step 3: 实现路由**

`category` 与 `village` 用 `Literal` 或枚举校验，非法值 400。这些路由**只读库不回源**（内容数据不经 read_through）。

分页复用 Task 9 的 `DEFAULT_PAGE_SIZE` / `clamp_page_size` / `page` 越界返回空列表的约定，不另起一套。

**内容类路由的 `meta`**：规格 §6.1 规定成功响应统一为 `{data, meta}`，但只定义了官方数据的三种缓存态，未定义内容数据（无回源、无过期）。此处按统一信封补齐，取 `cache: "HIT"`、`fetched_at: <该行 updated_at 或 published_at>`、`age_seconds: null`、`ttl_seconds: 0` —— **这是计划层的补全决策，不是规格原文**；前端若需区分内容与官方数据，判 `ttl_seconds == 0` 即可。公告路由（Task 17）沿用同一约定。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/api/test_upgrade.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/api/routes/upgrade.py tests/api/test_upgrade.py
git commit -m "feat: 升级路线与升级条目查询接口"
```

---

### Task 17: 公告 API

**Files:**
- Create: `migrations/versions/0007_announcements.py`
- Modify: `app/db/models.py`
- Create: `app/api/routes/content.py`
- Test: `tests/db/test_announcements.py`
- Test: `tests/api/test_announcements.py`

**Interfaces:**
- Consumes: 无新依赖
- Produces:
  - ORM `Announcement`（列见规格 §5.5）；`is_published` 过滤，`is_pinned` 优先排序
  - 路由：`GET /api/v1/announcements?category=&page=&page_size=`、`GET /api/v1/announcements/{id}`

- [ ] **Step 1: 写失败测试**

```python
async def test_unpublished_announcement_is_hidden(session):
    session.add(Announcement(title="草稿", body="x", category="notice",
                             is_published=False))
    await session.commit()
    # 断言列表接口查不到它，但后台可见
```

```python
async def test_announcements_order_pinned_first(client):
    # 插入 1 条置顶 + 2 条普通，断言置顶在首位
```

```python
async def test_announcement_detail_returns_404_when_missing(client):
    resp = await client.get("/api/v1/announcements/99999")
    assert resp.status_code == 404
```

- [ ] **Step 2: 运行测试确认失败**

Run: `alembic upgrade head && pytest tests/db/test_announcements.py tests/api/test_announcements.py -v`
Expected: FAIL

- [ ] **Step 3: 实现模型、迁移与路由**

排序 `ORDER BY is_pinned DESC, published_at DESC`。`published_at` 为 `TIMESTAMPTZ | None`，列表查询过滤 `is_published.is_(True)`。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/db/ tests/api/ -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/db/models.py app/api/routes/content.py migrations/versions/0007_announcements.py tests/
git commit -m "feat: 公告表与公告查询接口"
```

---

### Task 18: 投稿 API 与审核流转

**Files:**
- Create: `migrations/versions/0008_submissions.py`
- Modify: `app/db/models.py`
- Create: `app/content/submissions.py`
- Create: `app/api/routes/submissions.py`
- Test: `tests/content/test_submissions.py`
- Test: `tests/api/test_submissions.py`

**Interfaces:**
- Consumes: `Announcement`（Task 17 无关，仅共处 `content/` 包）
- Produces:
  - ORM `Submission`（列见规格 §5.5）；`ArmyComposition`、`ArmyCompositionItem`、`BaseLayout`（规格 §5.5）
  - `app/content/submissions.py`：`class SubmissionType` StrEnum、`class SubmissionStatus` StrEnum；`async def approve_submission(session: AsyncSession, submission: Submission) -> ArmyComposition | BaseLayout`
  - 路由：`POST /api/v1/submissions`、`GET /api/v1/submissions/{id}`

- [ ] **Step 1: 写失败测试**

```python
async def test_submit_army_composition_returns_pending(client):
    resp = await client.post("/api/v1/submissions", json={
        "type": "army_composition", "title": "TH16猪流",
        "payload": {"th_level": 16,
                    "items": [{"category": "troop", "name": "Hog Rider",
                               "quantity": 30, "level": 14}]}})
    assert resp.status_code == 201
    assert resp.json()["data"]["status"] == "pending"
```

```python
async def test_submit_rejects_empty_items_list(client):
    # payload.items == [] → 400，理由：空阵容无意义
```

```python
async def test_approve_creates_army_composition_and_items(session):
    sub = Submission(type="army_composition", title="x", status="pending",
                     payload={"th_level": 16, "items": [...]})
    session.add(sub); await session.commit()
    result = await approve_submission(session, sub)
    assert isinstance(result, ArmyComposition)
    items = (await session.execute(
        select(ArmyCompositionItem).where(
            ArmyCompositionItem.composition_id == result.id))).scalars().all()
    assert len(items) == 1
    assert sub.status == "approved"
    assert sub.source_site == "user_submission"
```

```python
async def test_approve_submission_twice_does_not_duplicate(session):
    # 第二次调用应抛 ValueError 或返回既有记录，断言 ArmyComposition 总数为 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `alembic upgrade head && pytest tests/content/test_submissions.py tests/api/test_submissions.py -v`
Expected: FAIL

- [ ] **Step 3: 实现模型与迁移**

`Submission.payload` 为 `JSONB`。`ArmyComposition` 与 `BaseLayout` 共享 `source_url`、`source_site`、`content_hash`、`copy_count`、`is_published` 字段（规格 §5.5），便于二期统一按热度排序。

- [ ] **Step 4: 实现审核流转**

`approve_submission` 单事务内：校验 `status == "pending"` 否则抛 `ValueError` → 按 `type` 创建对应正式记录并逐项创建 `ArmyCompositionItem` → 回填 `submission.status = "approved"`、`reviewed_at`。设置 `source_site = "user_submission"`、`content_hash = sha256(type + title + payload 规范化 JSON)`。

- [ ] **Step 5: 实现路由**

`POST /submissions` 校验：`type` 合法、`title` 非空且 ≤ 100 字、`payload.items` 非空数组（阵型类型则要求 `layout_link` 或 `image_path` 至少有一个）。

- [ ] **Step 6: 运行测试确认通过**

Run: `pytest tests/content/ tests/api/ -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add app/db/models.py app/content/submissions.py app/api/routes/submissions.py migrations/versions/0008_submissions.py tests/
git commit -m "feat: 投稿接口与审核流转"
```

---

### Task 19: SQLAdmin 后台

**Files:**
- Create: `app/api/routes/admin.py`
- Modify: `app/main.py`
- Create: `tests/fixtures/`（无需新增）
- Test: `tests/api/test_admin.py`

**Interfaces:**
- Consumes: 全部 ORM 模型、`Settings`
- Produces: `app/api/routes/admin.py` 中的 `class AdminAuth(AuthenticationBackend)`，认证单一管理员账号（凭据来自环境变量 `ADMIN_USERNAME` / `ADMIN_PASSWORD`）；`def build_admin(engine, settings) -> Admin`；`GET /admin` 返回登录页

- [ ] **Step 1: 写失败测试**

```python
async def test_admin_requires_login(client):
    resp = await client.get("/admin", follow_redirects=False)
    assert resp.status_code in (302, 307)

async def test_admin_login_page_is_served_after_auth(client, admin_credentials):
    resp = await client.post("/admin/login", data=admin_credentials, follow_redirects=True)
    assert resp.status_code == 200
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/api/test_admin.py -v`
Expected: FAIL —— 404

- [ ] **Step 3: 实现 `admin.py`**

`AdminAuth` 的 `login` / `logout` / `authenticate` 三个方法用 `secrets.compare_digest` 比对环境变量中的凭据—— **不用明文比较，也不在代码里硬编码任何账号密码**。

`build_admin` 中为每个模型注册 `ModelView`：

| ModelView | 关键配置 |
| --- | --- |
| `AnnouncementView` | `column_list` 含 title/category/is_pinned/is_published/published_at |
| `UpgradeItemView` | 支持按 `category` / `village` / `name` 过滤；这是补齐 `name_zh` 与 `builder_count` 的工作界面 |
| `UpgradeRouteView` | `form_excluded_columns` 排除 `created_at` |
| `SubmissionView` | **只读列表 + 一个「通过」动作按钮**，动作调用 `approve_submission` |
| `ArmyCompositionView` / `BaseLayoutView` | 只读（内容来自投稿与后台） |
| `CollectorRunView` | 只读，按 `started_at` 倒序 |
| `Ranking` / `Clan` / `Player` | **全部只读**，禁止后台手改官方数据 |
| `Submission` 之外的所有采集表 | **不注册**到后台（避免误删） |

在 `create_app()` 中 `app.mount("/admin", build_admin(engine, settings))`。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/api/test_admin.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/api/routes/admin.py app/main.py tests/api/test_admin.py
git commit -m "feat: SQLAdmin 后台与投稿审核动作"
```

---

### Task 20: 部署配置与上线清单

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `deploy/nginx.conf`
- Create: `deploy/certbot-renew.sh`
- Create: `deploy/backup.sh`
- Create: `docs/deployment.md`
- Test: `tests/test_deployment_config.py`

**Interfaces:**
- Consumes: `Settings`（容器内环境变量）
- Produces: 可 `docker compose up -d` 启动的三服务栈

- [ ] **Step 1: 写配置校验测试**

`tests/test_deployment_config.py` 解析 `docker-compose.yml` 与 `deploy/nginx.conf`（用 `yaml` 与纯文本断言）：

```python
def test_compose_does_not_expose_db_port_to_host():
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    assert "ports" not in compose["services"]["postgres"]

def test_nginx_proxies_api_and_media():
    conf = Path("deploy/nginx.conf").read_text(encoding="utf-8")
    assert "location /api/" in conf
    assert "location /media/" in conf

def test_env_example_contains_no_real_secret():
    env = Path(".env.example").read_text(encoding="utf-8")
    for line in env.splitlines():
        if line.startswith(("COC_API_TOKEN=", "ADMIN_PASSWORD=")):
            assert line.split("=", 1)[1] == "", f"示例文件不得含真实值: {line}"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_deployment_config.py -v`
Expected: FAIL —— 文件不存在

- [ ] **Step 3: 编写 `Dockerfile`**

多阶段：`builder` 阶段 `pip install --no-cache-dir .` 构建到 `/opt/venv`；`runtime` 阶段仅 `COPY --from=builder /opt/venv`，非 root 用户，入口 `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1`。

**`--workers 1` 是硬性要求**（Global Constraints 里的单副本设计），需在 Dockerfile 的 `CMD` 中固定并在 `docs/deployment.md` 中注明原因。

- [ ] **Step 4: 编写 `docker-compose.yml` 与 `nginx.conf`**

三服务：`api`（`build: .`，不暴露端口）、`postgres:16-alpine`（`volumes` 持久化，无 `ports`）、`nginx`（80/443 暴露，挂载 `deploy/nginx.conf` 与 `./media:/data/media:ro`）。卷 `media` 同时以可写方式挂给 `api`。

nginx：`/api/` 与 `/admin/` 反代到 `api:8000`；`/media/` 用 `alias /data/media/`；`proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`（Task 14 的限流依赖它）。

- [ ] **Step 5: 编写运维脚本**

- `deploy/certbot-renew.sh`：`certbot renew --quiet` + `nginx -s reload`
- `deploy/backup.sh`：`pg_dump` 到 `backups/db-$(date +%F).sql` + `tar` 打包 media 卷，保留 14 天

- [ ] **Step 6: 编写 `docs/deployment.md`**

严格按规格 §8.3 的八步写，每步给出可复制命令。特别要显式提醒第 8 步「小程序后台配置 request 合法域名」——漏掉这一步小程序端完全调不通，且排查困难。

- [ ] **Step 7: 运行测试确认通过**

Run: `pytest tests/test_deployment_config.py -v`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add Dockerfile docker-compose.yml deploy/ docs/deployment.md .env.example tests/test_deployment_config.py
git commit -m "chore: Docker Compose 部署配置与上线文档"
```

---

# Phase B 验收

- [ ] **Step B1**: `pytest` 全绿
- [ ] **Step B2**: `docker compose up -d` 从零启动，`/readyz` 返回 200
- [ ] **Step B3**: `python -m app.cli import-game-data` 导入 2073 行升级数据
- [ ] **Step B4**: 后台登录、补齐 `name_zh`、录入一条公告、审核一条投稿
- [ ] **Step B5**: 手动冒烟 —— 用真实 Token 跑一次 `/api/v1/clans/%232PP` 与 `/api/v1/rankings/clans`
- [ ] **Step B6**: 提交 Phase B 汇总

---

## 附：任务依赖关系

```
Task 1  骨架
  └─> Task 2  错误与限流
        └─> Task 4  CocClient
              └─> Task 5  官方接口封装
Task 3  数据库基座与维表
  ├─> Task 6  实体表
  │     ├─> Task 7  映射器（依赖 5 的 tag 处理）
  │     │     └─> Task 8  读时旁路（依赖 2）
  │     │           └─> Task 9  查询 API ──> Task 10  战报 API
  │     └─> Task 11 排行榜表 ──> Task 13  排行榜 API
  └─> Task 12  调度器（依赖 5、11）
Task 14 readyz 与限流（依赖 2）
Task 15 升级数据导入（依赖 3）
  └─> Task 16 升级 API
Task 17 公告（依赖 3）──> Task 18 投稿（依赖 17）
Task 19 后台（依赖 18）
Task 20 部署（依赖 19）
```

关键串行点：**Task 3 → Task 6 → Task 7 → Task 8 → Task 9** 是最长依赖链，无法并行。若需提速，Task 11（排行榜表）与 Task 12（调度器）可在 Task 8 完成后与 Task 9 并行推进。