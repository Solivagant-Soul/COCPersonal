# COCPersonal MVP 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `COCPersonal` 单仓内交付「COCBack 后端（全量搬入）+ Vue3 网页前端（查询 + 排行榜）」的 MVP，可在 Windows 本地跑通、并在 Linux 用 Docker Compose 部署。

**Architecture:** 前后端分离、同仓两顶级目录（`backend/`、`frontend/`）。后端沿用 COCBack 的 FastAPI + SQLAlchemy async + PostgreSQL，单进程一体（API + 采集调度器）；新增一个 dev 夹具上游，使无真实 Token 时查询/排行也能返回真实形状的数据。前端 Vue3 SPA 经 nginx 托管静态文件并反代 `/api`。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy(async) / alembic / PostgreSQL 16；Vue 3 / Vite / TypeScript / Element Plus / Vue Router / Pinia / axios / Vitest；Nginx / Docker Compose。

**Spec:** `docs/superpowers/specs/2026-10-16-cocpersonal-design.md`

## Global Constraints

- Python `>=3.12`；`sqlalchemy>=2.0,<2.1`（不得放宽）；镜像 `CMD` 固定 `--workers 1`（令牌桶/调度器/缓存均为进程内）。
- 后端保留全部既有功能代码；本计划只新增三处：`backend/README.md`、dev 夹具上游、`seed-dev-rankings` CLI。
- 接口契约：成功体 `{"data":...,"meta":{"cache","fetched_at","age_seconds","ttl_seconds"}}`；**`meta.cache` 大写** `HIT`/`MISS`/`STALE`；错误体 `{"error":{"code","message","upstream_reason"}}`；`page_size` 上限 50 且**超限截断为 50 返回 200**（不是 422）；限流 60 次/分/IP，`/healthz`、`/readyz` 豁免。
- 前端导航**只留「查询」「排行榜」**；投稿/公告/后台不进网页导航。
- 本地数据库：`C:\pgportable` 免安装 PostgreSQL，`127.0.0.1:5433`，trust 认证（本机虚拟化在固件层关闭，Docker/WSL2 不可用）。
- 部署默认 **HTTP-only**；HTTPS 留可开关，不实现。
- 提交信息用中文 + conventional prefix（`feat:` `fix:` `test:` `chore:` `docs:`），一个任务一个提交。
- Windows 唯一可用 bash 是 `D:\Program Files\Git\bin\bash.exe`（PATH 上的 `bash` 是未安装 WSL 的转发桩）。

## Review Focus

规范是愿景文档，它对以下输入保持沉默，但沉默不等于允许崩溃。每条都在拥有该代码的任务里配了测试：

1. **响应信封损坏**（后端挂了返回 HTML / `meta` 缺失）→ 前端须显示「错误卡片 + 重试」，不得白屏。（Task 5）
2. **`meta.cache === 'STALE'`**（回源失败但有旧数据，HTTP 200）→ 页面须照常渲染并可提示「数据可能过期」，不得当错误。（Task 5、7）
3. **tag 含全角＃ / 小写 / 无 `#` / 非法字符** → `normalizeTag` 归一化后再发请求，非法则不发请求、就地提示。（Task 6、7）
4. **超大数值**（trophies/points 达 `1e21` 量级）→ `formatNumber`/`formatCompact` 不得输出科学计数法、不得丢数量级。（Task 6）
5. **`page_size` 超 50** → 后端截断为 50 返回 200；前端传大值不得报错、不得当 422 处理。（Task 8）

---

### Task 1: 搬入后端骨架 + 仓库骨架

**Files:**
- Create: `backend/`（整目录，来自 `..\COCBack`）
- Create: `backend/README.md`、`.gitignore`（仓库根）
- Modify: `AGENTS.md`（仓库根，仅补一行结构说明；完整文档在 Task 11）

**Interfaces:**
- Consumes: `..\COCBack` 现有文件。
- Produces: `backend/` 包 `app`（`create_app()`、`app.cli`、`alembic` 迁移链）；后续任务在其上增改。

- [ ] **Step 1: 复制后端**

```powershell
cd F:\Python_file\MiniProgram\COCPersonal
$src = "F:\Python_file\MiniProgram\COCBack"
New-Item -ItemType Directory -Force backend | Out-Null
foreach ($d in "app","migrations","tests","deploy") { Copy-Item -Recurse -Force "$src\$d" "backend\$d" }
foreach ($f in "pyproject.toml","alembic.ini","Dockerfile","AGENTS.md",".env.example",".gitignore","docker-compose.test.yml") { Copy-Item -Force "$src\$f" "backend\$f" }
Get-ChildItem -Recurse -Directory backend -Filter __pycache__ | Remove-Item -Recurse -Force
```
说明：**不复制** `docker-compose.yml`（由根 Task 10 的组合 compose 取代）、`.env`（本地私有）、`.git`/`.cache`/`.pytest_cache`/`.superpowers`/`docs`。`backend/AGENTS.md` 作为后端环境陷阱的权威参考保留。

- [ ] **Step 2: 新建 `backend/README.md`**（`Dockerfile` 有 `COPY pyproject.toml README.md ./`，缺失则镜像构建失败）

内容至少：项目名 `coc-backend`、一句用途、`python -m pytest -q` 运行测试、`.env.example` → `.env` 说明。

- [ ] **Step 3: 新建仓库根 `.gitignore`**

```gitignore
# Python
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.env
# Node
node_modules/
dist/
# 本地/编辑器
.cache/
.superpowers/
.DS_Store
```

- [ ] **Step 4: 起本地 PG 并跑后端测试**

```powershell
C:\pgportable\pgsql\bin\pg_isready.exe -h 127.0.0.1 -p 5433 -U postgres
# 未起则： Start-Process "C:\pgportable\pgsql\bin\postgres.exe" -ArgumentList "-D","C:\pgportable\data","-p","5433","-h","127.0.0.1" -WindowStyle Hidden
cd backend; python -m pytest -q
```
Expected: 全绿（COCBack 基线为 486 项）。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: 全量搬入 COCBack 后端并建立仓库骨架"
```

---

### Task 2: dev 夹具上游（无真实 Token 也能应答）

**Files:**
- Create: `backend/app/coc/devfixtures.py`
- Create: `backend/tests/coc/test_devfixtures.py`
- Modify: `backend/app/main.py`（`lifespan` 里构造 `CocClient` 处）

**Interfaces:**
- Consumes: `tests/fixtures/{player_profile,clan_detail,locations,ranking_clans}.json`（均为官方形状，带 `_source`/`_todo`）。
- Produces:
  - `is_placeholder_token(token: str) -> bool`
  - `class FixtureTransport(httpx.AsyncBaseTransport)`，`async def handle_async_request(self, request: httpx.Request) -> httpx.Response`，按 `request.url.path` 返回夹具。
  - `app/main.py` 中：`transport = FixtureTransport() if is_placeholder_token(settings.coc_api_token) else None`，传给 `CocClient(transport=transport)`。

- [ ] **Step 1: 写失败测试 `tests/coc/test_devfixtures.py`**

```python
import httpx
from app.coc.devfixtures import FixtureTransport, is_placeholder_token

def test_placeholder_detection():
    assert is_placeholder_token("")
    assert is_placeholder_token("PLACEHOLDER")
    assert not is_placeholder_token("test-token")

async def test_transport_maps_player_path():
    t = FixtureTransport()
    resp = await t.handle_async_request(httpx.Request("GET", "https://x/v1/players/%239QJ8L0"))
    assert resp.status_code == 200
    assert resp.json()["tag"].startswith("#")

async def test_transport_unknown_path_is_404_notfound():
    t = FixtureTransport()
    resp = await t.handle_async_request(httpx.Request("GET", "https://x/v1/nope"))
    assert resp.status_code == 404
    assert resp.json()["reason"] == "notFound"

async def test_transport_maps_rankings_path():
    t = FixtureTransport()
    resp = await t.handle_async_request(httpx.Request("GET", "https://x/v1/rankings/clans?locationId=32000001"))
    assert resp.status_code == 200
    assert isinstance(resp.json()["items"], list)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend; python -m pytest tests/coc/test_devfixtures.py -q`
Expected: FAIL（`ModuleNotFoundError: app.coc.devfixtures`）。

- [ ] **Step 3: 实现 `app/coc/devfixtures.py`**

要点：`__init__` 里 `Path` 定位到 `tests/fixtures/`（相对仓库根，可用 `Path(__file__).resolve().parents[2] / "tests" / "fixtures"`）；`handle_async_request` 用 `request.url.path` 后缀匹配：
`/players/` → `player_profile.json`；`/clans/search` → 返回 `{"items": [...]}`（可用 `clan_detail` 造一条）；`/clans/` → `clan_detail.json`；`/locations` → `locations.json`；`/rankings/clans` → `ranking_clans.json`；其他 → `httpx.Response(404, json={"reason": "notFound"})`。均返回 `httpx.Response(200, json=<dict>)`。

- [ ] **Step 4: 运行确认通过**

Run: `cd backend; python -m pytest tests/coc/test_devfixtures.py -q`
Expected: PASS。

- [ ] **Step 5: 接入 `app/main.py`**（仅改 `lifespan` 里 `CocClient(...)` 构造：按 `is_placeholder_token` 传 `transport`，token 为空时传 `"PLACEHOLDER"`）。

- [ ] **Step 6: 回归 + Commit**

Run: `cd backend; python -m pytest -q`
Expected: 全绿。

```bash
git add backend/app/coc/devfixtures.py backend/app/main.py backend/tests/coc/test_devfixtures.py
git commit -m "feat: 新增 dev 夹具上游，无真实 Token 也能应答查询"
```

---

### Task 3: `seed-dev-rankings` CLI（排行榜种子数据）

**Files:**
- Create: `backend/app/devseed.py`
- Create: `backend/tests/test_devseed.py`
- Modify: `backend/app/cli.py`（新增子命令）

**Interfaces:**
- Consumes: `app.collector.jobs._upsert.upsert_all(session, model, rows, conflict)`；`app.collector.rankings_service.replace_rankings(session, kind, location_id, league_id, season_id, items, now=None) -> int`、`RankingKind`；`app.db.models.Location/Ranking`。
- Produces: `async def seed_dev_rankings(session, *, location_id: int | None = None, fixtures_dir: Path | None = None) -> dict[str, int]`，返回 `{"locations": n, "rankings": m}`。

- [ ] **Step 1: 写失败测试 `tests/test_devseed.py`**

```python
from sqlalchemy import select
from app.db.models import Ranking
from app.devseed import seed_dev_rankings

async def test_seed_writes_rankings(session):
    counts = await seed_dev_rankings(session, location_id=32000001)
    assert counts["rankings"] > 0
    rows = (await session.execute(select(Ranking).where(Ranking.kind == "clans"))).scalars().all()
    assert rows and rows[0].location_id == 32000001

async def test_seed_then_api_returns_items(client, session):
    await seed_dev_rankings(session, location_id=32000001)
    resp = await client.get("/api/v1/rankings/clans?locationId=32000001")
    assert resp.status_code == 200
    assert resp.json()["data"]["items"]
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend; python -m pytest tests/test_devseed.py -q`
Expected: FAIL（`ModuleNotFoundError: app.devseed`）。

- [ ] **Step 3: 实现 `app/devseed.py`**：读 `locations.json` → `Location(id, name, is_country, country_code)` 列表 → `upsert_all(session, Location, rows, "id")`；读 `ranking_clans.json` 的 `items` → `await replace_rankings(session, RankingKind.clans, location_id, None, None, items)`；`location_id` 缺省用 `32000001`；`await session.commit()`。

- [ ] **Step 4: 运行确认通过**

Run: `cd backend; python -m pytest tests/test_devseed.py -q`
Expected: PASS。

- [ ] **Step 5: 给 `app/cli.py` 加子命令**：`seed-dev-rankings`（参数 `--location` 默认 `32000001`），`main()` 里 `asyncio.run` 调 `seed_dev_rankings`（自建 session，参照 `_import_with_own_session` 的写法），打印 `counts`。

- [ ] **Step 6: 验证 CLI + Commit**

Run: `cd backend; python -m app.cli seed-dev-rankings`（需 `.env`）
Expected: 打印写入条数且 > 0。

```bash
git add backend/app/devseed.py backend/app/cli.py backend/tests/test_devseed.py
git commit -m "feat: 新增 seed-dev-rankings 命令灌入榜单夹具数据"
```

---

### Task 4: 前端脚手架（Vite + Vue3 + TS + Element Plus + Router + Pinia + Vitest）

**Files:**
- Create: `frontend/{package.json,vite.config.ts,tsconfig.json,tsconfig.node.json,index.html,env.d.ts}`
- Create: `frontend/src/{main.ts,App.vue}`
- Create: `frontend/src/router/index.ts`
- Create: `frontend/src/layouts/MainLayout.vue`
- Create: `frontend/src/styles/main.css`
- Test: `frontend/src/layouts/MainLayout.spec.ts`

**Interfaces:**
- Produces: 可构建的 Vue3 应用；路由名 `query`(`/`)、`player`(`/players/:tag`)、`clan`(`/clans/:tag`)、`rankings`(`/rankings`)；`MainLayout` 左侧导航仅「查询」「排行榜」。

- [ ] **Step 1: 初始化工程**（`npm create vite@latest frontend -- --template vue-ts`），装依赖：

```bash
cd frontend
npm i vue-router pinia element-plus axios
npm i -D vitest @vue/test-utils jsdom @vitejs/plugin-vue typescript
```

- [ ] **Step 2: 配置 `vite.config.ts`**：`plugins:[vue()]`；`server.proxy = { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } }`；`test: { environment: 'jsdom', globals: true }`；`package.json` 脚本加 `"test": "vitest run"`。

- [ ] **Step 3: 写失败测试 `src/layouts/MainLayout.spec.ts`**

```ts
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import MainLayout from './MainLayout.vue'
import { describe, it, expect } from 'vitest'

const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/', name: 'query', component: { template: '<div/>' } },
  { path: '/rankings', name: 'rankings', component: { template: '<div/>' } },
]})

describe('MainLayout', () => {
  it('导航只含查询与排行榜', async () => {
    const w = mount(MainLayout, { global: { plugins: [router] } })
    const text = w.text()
    expect(text).toContain('查询')
    expect(text).toContain('排行榜')
    expect(text).not.toContain('投稿')
    expect(text).not.toContain('公告')
  })
})
```

- [ ] **Step 4: 运行确认失败**：Run `cd frontend; npm run test` → FAIL。

- [ ] **Step 5: 实现 `MainLayout.vue`**（Element Plus `el-container` + `el-aside`（`el-menu` 两项）+ `el-main` 内 `<router-view/>`）、`router/index.ts`（上述 4 条路由，先指向占位组件，Task 7/8 替换）、`main.ts`（挂 `router`、`pinia`、`ElementPlus`、`styles/main.css`）。

- [ ] **Step 6: 运行确认通过 + 构建**

Run: `cd frontend; npm run test; npm run build`
Expected: 测试 PASS，`build` 产出 `dist/`。

- [ ] **Step 7: Commit**

```bash
git add frontend
git commit -m "feat: 建立 Vue3+ElementPlus 前端脚手架与两项导航"
```

---

### Task 5: 前端 API 客户端 + 契约单测

**Files:**
- Create: `frontend/src/api/request.ts`
- Create: `frontend/src/api/types.ts`
- Test: `frontend/src/api/request.spec.ts`

**Interfaces:**
- Consumes: 后端信封契约（Global Constraints）。
- Produces:
  - `interface Meta { cache: string | null; fetchedAt: string | null; ageSeconds: number | null; ttlSeconds: number | null }`
  - `interface Envelope<T> { data: T; meta: Meta }`
  - `class ApiError extends Error { code: string; status: number }`
  - `async function request<T>(path: string, opts?: { method?: 'GET'|'POST'; params?: Record<string, unknown>; data?: unknown }): Promise<Envelope<T>>`

- [ ] **Step 1: 写失败测试 `src/api/request.spec.ts`**（用 `axios-mock-adapter` 或直接 `vi.mock('axios')`；以下断言是契约核心）

```ts
// 1) 成功：meta 蛇形转驼峰，data 透传
//    mock 200 {data:{tag:'#A'},meta:{cache:'HIT',fetched_at:'t',age_seconds:0,ttl_seconds:60}}
//    -> {data:{tag:'#A'}, meta:{cache:'HIT',fetchedAt:'t',ageSeconds:0,ttlSeconds:60}}
// 2) age_seconds=0 必须保留为 0，不能因 falsy 变 null
// 3) STALE 不特判：cache:'STALE' 时仍 resolve（不 reject）
// 4) 非 2xx + 有 error 体 -> ApiError(code=后端code, status)
// 5) 非 2xx + 无 error 体 -> 4xx 归 BAD_REQUEST，5xx 归 UPSTREAM_UNAVAILABLE
// 6) 2xx 但 body 是数组/字符串 -> BAD_RESPONSE
// 7) 2xx 但 meta 缺失/null -> BAD_RESPONSE
// 8) 网络失败 -> NETWORK_ERROR, status 0
```

- [ ] **Step 2: 运行确认失败**：Run `cd frontend; npm run test` → FAIL。

- [ ] **Step 3: 实现 `request.ts`/`types.ts`**：axios 实例 `baseURL: import.meta.env.VITE_API_BASE || ''`；成功分支**先**判 body 是非 null 非数组对象、再判 `meta != null`，否则 `throw new ApiError('BAD_RESPONSE', ..., status)`；`toCamelMeta` 用 `=== undefined ? null : v`（**不可**用 `v || null`）；错误分支优先透传 `body.error.code`（须为非空字符串），否则按 status 归一；catch 网络错误 → `ApiError('NETWORK_ERROR', ..., 0)`。**不特判 STALE。**

- [ ] **Step 4: 运行确认通过**：Run `cd frontend; npm run test` → PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api
git commit -m "feat: 前端 API 客户端，移植信封与错误码契约"
```

---

### Task 6: 前端格式化工具（移植 `format.js`）

**Files:**
- Create: `frontend/src/utils/format.ts`
- Test: `frontend/src/utils/format.spec.ts`

**Interfaces:**
- Consumes: `..\COC\utils\format.js`（行为契约）。
- Produces: `formatNumber(n): string`、`formatCompact(n): string`、`formatRelativeTime(iso, nowMs): string`、`normalizeTag(input): string | null`、`enumLabel(group, value): string`。

- [ ] **Step 1: 写失败测试 `src/utils/format.spec.ts`**

```ts
// formatNumber: null/undefined/NaN/boolean/'' -> '-'; 12345 -> '12,345'
// 大数防科学计数法: formatNumber(1e21) -> '1,000,000,000,000,000,000,000'
// formatCompact: 12345 -> '1.2万'; 1.5e8 -> '1.5亿'; 9999 -> '9,999'
// formatCompact(3e29) 不得塌成 '3亿'（数量级必须保住）
// normalizeTag: '＃8qu8j9j' -> '#8QU8J9J'; 'abc' -> null; '' -> null
// formatRelativeTime: now-30s -> '刚刚'; 未来时间 -> '刚刚'
```

- [ ] **Step 2: 运行确认失败**：Run `cd frontend; npm run test` → FAIL。

- [ ] **Step 3: 实现 `format.ts`**：逐函数移植 `..\COC\utils\format.js` 的算法（`toFiniteNumber`、`expandExponential`、`groupThousands`、`oneDecimal` 的两分支去尾零、`TAG_RE=/^[0-9A-Z]{3,10}$/`、`ENUM_LABELS` 表），加 TS 类型。

- [ ] **Step 4: 运行确认通过**：Run `cd frontend; npm run test` → PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils
git commit -m "feat: 移植前端格式化工具（含大数防护与 tag 归一化）"
```

---

### Task 7: 查询页面（首页 / 玩家详情 / 部落详情）

**Files:**
- Create: `frontend/src/api/endpoints.ts`
- Create: `frontend/src/components/{TagInput.vue,ErrorCard.vue,LoadingBlock.vue,StatGrid.vue}`
- Create: `frontend/src/pages/{QueryHome.vue,PlayerDetail.vue,ClanDetail.vue}`
- Modify: `frontend/src/router/index.ts`（接真实页面）
- Test: `frontend/src/components/TagInput.spec.ts`、`frontend/src/pages/PlayerDetail.spec.ts`

**Interfaces:**
- Consumes: `request<T>`（Task 5）、`normalizeTag`/`formatNumber`/`formatCompact`/`enumLabel`（Task 6）、后端 `GET /api/v1/players/{tag}`、`GET /api/v1/clans/{tag}`。
- Produces: `getPlayer(tag)`, `getClan(tag)`、`getLocations()`, `getRankings(kind, locationId, page, pageSize)`（最后一个给 Task 8）、`ApiError` 驱动的统一错误卡片。

- [ ] **Step 1: 写失败测试 `src/components/TagInput.spec.ts`**

```ts
// 输入 '＃8qu8j9j' 点查询 -> emit('submit', '#8QU8J9J')
// 输入 'abc' -> 不 emit，显示校验提示（不构造注定 400 的请求）
```

- [ ] **Step 2: 写失败测试 `src/pages/PlayerDetail.spec.ts`**（mock `endpoints.ts`）

```ts
// 成功: 渲染 name/tag；带上 meta.cache
// STALE: cache==='STALE' 时仍渲染档案，并出现「数据可能过期」文案（不是错误卡片）
// 404 PLAYER_NOT_FOUND: 渲染 ErrorCard 且文案含「玩家不存在」
// BAD_RESPONSE: 渲染 ErrorCard（不白屏）
```

- [ ] **Step 3: 运行确认失败**：Run `cd frontend; npm run test` → FAIL。

- [ ] **Step 4: 实现**：`endpoints.ts`（typed 调用，tag 用 `encodeURIComponent`）；`TagInput.vue`（用 `normalizeTag` 校验后 `emit('submit', tag)`）；`ErrorCard.vue`（按 `ApiError.code` 给中文文案 + 重试按钮）；玩家详情用 `el-descriptions` + `formatNumber`；部落详情同构（可复用 `StatGrid.vue`）；`router/index.ts` 接真实页面。

- [ ] **Step 5: 运行确认通过 + 构建**：Run `cd frontend; npm run test; npm run build` → PASS。

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "feat: 查询首页、玩家详情、部落详情页（含错误卡片与 STALE 提示）"
```

---

### Task 8: 排行榜页面

**Files:**
- Create: `frontend/src/pages/Rankings.vue`
- Create: `frontend/src/components/RankingTable.vue`
- Modify: `frontend/src/router/index.ts`
- Test: `frontend/src/pages/Rankings.spec.ts`

**Interfaces:**
- Consumes: `getLocations()`、`getRankings(kind, locationId, page, pageSize)`（Task 7）、后端 `GET /api/v1/locations`、`GET /api/v1/rankings/{clans|players|capitals|clans_builder_base|players_builder_base}`。
- Produces: 可切地区与榜单类型的排行榜表。

- [ ] **Step 1: 写失败测试 `src/pages/Rankings.spec.ts`**（mock `endpoints.ts`）

```ts
// 初始加载地区列表，默认选中夹具中的国家地区（如 China/32000001）
// 切换 kind 触发重新拉取，表格渲染 name/rank/trophies
// 空 items -> 显示「暂无数据」空态（不是错误）
// page_size 传 100（>50）-> 不报错；表格按后端返回渲染（后端会截断为 50）
```

- [ ] **Step 2: 运行确认失败**：Run `cd frontend; npm run test` → FAIL。

- [ ] **Step 3: 实现 `Rankings.vue` + `RankingTable.vue`**：`el-select`（地区）+ `el-radio-group`（榜单类型）+ `el-table` + `el-pagination`（`page-size` 默认 20，最大 50）。

- [ ] **Step 4: 运行确认通过 + 构建**：Run `cd frontend; npm run test; npm run build` → PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: 排行榜页面（地区+榜单类型切换）"
```

---

### Task 9: 本地端到端联调（验证任务）

**Files:** 无（仅验证；发现问题回到对应任务修）

**Interfaces:**
- Consumes: Task 1–8 全部产物；本地 PG、后端、Vite。
- Produces: 一份「本机手测通过」的结论（写进 Task 11 的 README）。

- [ ] **Step 1: 起三项**（分别后台起）

```powershell
C:\pgportable\pgsql\bin\pg_isready.exe -h 127.0.0.1 -p 5433 -U postgres   # PG 就绪
cd backend; Copy-Item .env.example .env   # 若尚未建；DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:5433/postgres，COC_API_TOKEN 留空
cd backend; python -m app.cli seed-dev-rankings
cd backend; python -m uvicorn app.main:app --reload --port 8000
cd frontend; npm run dev
```

- [ ] **Step 2: 后端自检**

Run: `curl.exe http://127.0.0.1:8000/healthz`；`curl.exe "http://127.0.0.1:8000/api/v1/players/%239QJ8L0"`
Expected: 200；玩家 payload 的 `data.tag` 形如 `#...`，`meta.cache` ∈ {MISS,HIT}。

- [ ] **Step 3: 浏览器手测**（`http://localhost:5173`）

逐项确认：查询首页输入合法 tag 跳详情；非法 tag 就地提示；玩家/部落详情渲染数值（千分位）；排行榜默认地区出数据、切 kind 正常；把后端停掉后页面出**错误卡片且可重试**（不白屏）。

- [ ] **Step 4: 记录 + Commit**

把「联调步骤与结论」写入 `docs/superpowers/plans/2026-10-16-cocpersonal-mvp.md` 末尾的「联调记录」小节点（或 README），提交。

```bash
git add -A
git commit -m "chore: 记录本地端到端联调结果"
```

---

### Task 10: 部署资产（前端 Dockerfile / nginx / Compose）

**Files:**
- Create: `frontend/Dockerfile`
- Create: `deploy/nginx.conf`
- Create: `docker-compose.yml`（仓库根）
- Create: `.env.example`（仓库根）
- Test: 静态校验（`docker compose config`；本机无 Docker 则人工审阅）

**Interfaces:**
- Consumes: `frontend/`（`npm run build` → `dist/`）、`backend/Dockerfile`（镜像 `api`）、`backend/deploy/backup.sh`（可选运维参考）。
- Produces: 单机三容器栈：`web`（对外 80）+ `api`（`:8000` 内部）+ `postgres`。

- [ ] **Step 1: 写 `frontend/Dockerfile`**（多阶段）

```dockerfile
FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
```
（`deploy/nginx.conf` 由 compose 挂载到 `/etc/nginx/conf.d/default.conf`。）

- [ ] **Step 2: 写 `deploy/nginx.conf`（HTTP-only，默认）**：`location / { root /usr/share/nginx/html; try_files $uri $uri/ /index.html; }`；`location /api/ { proxy_pass http://api:8000; }`；`/admin/`、`/media/`（alias + `autoindex off`）、`/healthz`、`/readyz`（`access_log off`）；**透传 `X-Forwarded-For`**；文件末尾保留注释版 `443 ssl` server 段作为 HTTPS 开关参考。

- [ ] **Step 3: 写根 `docker-compose.yml`**：`postgres`（`postgres:16-alpine`，卷 `pgdata`，healthcheck `pg_isready`）；`api`（`build: ./backend`，`depends_on` postgres healthy，环境同 COCBack 的 `api`，`APP_ROLE=all`）；`web`（`build: ./frontend`，`ports: ["80:80"]`，挂载 `./deploy/nginx.conf:/etc/nginx/conf.d/default.conf:ro`，`depends_on: [api]`）。**只有 web 映射端口。**

- [ ] **Step 4: 写根 `.env.example`**：`POSTGRES_DB/POSTGRES_USER/POSTGRES_PASSWORD/COC_API_TOKEN/COC_BASE_URL/APP_ROLE/ADMIN_USERNAME/ADMIN_PASSWORD/ADMIN_SECRET_KEY/PUBLIC_BASE_URL/RATE_LIMIT_PER_MINUTE` 占位（值留空）。

- [ ] **Step 5: 校验**

Run: `docker compose config`（本机若 Docker 不可用，逐行人工核对服务名/卷/端口/环境变量）
Expected: 配置无语法错误，服务为 `postgres`/`api`/`web`。

- [ ] **Step 6: Commit**

```bash
git add frontend/Dockerfile deploy/nginx.conf docker-compose.yml .env.example
git commit -m "feat: 组合部署资产（nginx 托管 SPA + 反代 api + compose）"
```

---

### Task 11: 文档（README / AGENTS / 说明）

**Files:**
- Create: `README.md`（仓库根）
- Modify: `AGENTS.md`（仓库根）

**Interfaces:**
- Consumes: 前 10 个任务的产物与 Task 9 的联调结论。
- Produces: 面向新人的开发/构建/部署说明。

- [ ] **Step 1: 写根 `README.md`**：项目简介；结构（`backend/`、`frontend/`、`deploy/`）；**本地开发**（起 PG → 后端 `.env` + `seed-dev-rankings` + uvicorn → 前端 `npm i && npm run dev` → 浏览器 `:5173`）；**构建**（`npm run build`、`pytest`）；**部署**（`cp .env.example .env` 填必填项 → `docker compose up -d --build`）；HTTPS 开关说明；夹具数据说明（`_source`/`_todo`）。

- [ ] **Step 2: 更新根 `AGENTS.md`**：把「待补充」替换为真实命令与结构；保留「每次修改及时提交本地 git」；补后端硬约束引用（指向 `backend/AGENTS.md`）与前端命令。

- [ ] **Step 3: 校验链接与命令**：按 README 逐条命令核对路径存在（不实际起 Docker）。

- [ ] **Step 4: Commit**

```bash
git add README.md AGENTS.md
git commit -m "docs: 补齐开发/构建/部署说明并更新 AGENTS.md"
```

---

## 联调记录

（Task 9 完成后在此填写：起服务的命令、手测通过项、遇到的问题与修复。）
