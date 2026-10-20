# COCPersonal MVP 实施计划

> **状态：11 / 11 任务全部完成并已提交**（2026-10-17，`main` 分支，自 `0b56079` 起）。
> 本机可做的验证都做了：后端 501 passed、前端 36 passed、`npm run build` 通过、真实进程
> HTTP 端到端通过，**浏览器 DOM 手测也已补做通过**（Task 9 Step 3 原先被 AdGuard 阻断，
> 已重跑；并在那次手测中揪出一个缓存缺陷并修掉，见「联调记录 → 三处后端潜伏缺陷」）。
> **只剩一项本机做不到**（`docker compose up`）—— 原因与补做方式见文末「联调记录 →
> 未完成项」——别把「全绿」当成「全好」。

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

- [x] **Step 1: 复制后端**

```powershell
cd F:\Python_file\MiniProgram\COCPersonal
$src = "F:\Python_file\MiniProgram\COCBack"
New-Item -ItemType Directory -Force backend | Out-Null
foreach ($d in "app","migrations","tests","deploy") { Copy-Item -Recurse -Force "$src\$d" "backend\$d" }
foreach ($f in "pyproject.toml","alembic.ini","Dockerfile","AGENTS.md",".env.example",".gitignore","docker-compose.test.yml") { Copy-Item -Force "$src\$f" "backend\$f" }
Get-ChildItem -Recurse -Directory backend -Filter __pycache__ | Remove-Item -Recurse -Force
```
说明：**不复制** `docker-compose.yml`（由根 Task 10 的组合 compose 取代）、`.env`（本地私有）、`.git`/`.cache`/`.pytest_cache`/`.superpowers`/`docs`。`backend/AGENTS.md` 作为后端环境陷阱的权威参考保留。

- [x] **Step 2: 新建 `backend/README.md`**（`Dockerfile` 有 `COPY pyproject.toml README.md ./`，缺失则镜像构建失败）

内容至少：项目名 `coc-backend`、一句用途、`python -m pytest -q` 运行测试、`.env.example` → `.env` 说明。

- [x] **Step 3: 新建仓库根 `.gitignore`**

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

- [x] **Step 4: 起本地 PG 并跑后端测试**

```powershell
C:\pgportable\pgsql\bin\pg_isready.exe -h 127.0.0.1 -p 5433 -U postgres
# 未起则： Start-Process "C:\pgportable\pgsql\bin\postgres.exe" -ArgumentList "-D","C:\pgportable\data","-p","5433","-h","127.0.0.1" -WindowStyle Hidden
cd backend; python -m pytest -q
```
Expected: 全绿（COCBack 基线为 486 项）。

- [x] **Step 5: Commit**

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

- [x] **Step 1: 写失败测试 `tests/coc/test_devfixtures.py`**

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

- [x] **Step 2: 运行确认失败**

Run: `cd backend; python -m pytest tests/coc/test_devfixtures.py -q`
Expected: FAIL（`ModuleNotFoundError: app.coc.devfixtures`）。

- [x] **Step 3: 实现 `app/coc/devfixtures.py`**

要点：`__init__` 里 `Path` 定位到 `tests/fixtures/`（相对仓库根，可用 `Path(__file__).resolve().parents[2] / "tests" / "fixtures"`）；`handle_async_request` 用 `request.url.path` 后缀匹配：
`/players/` → `player_profile.json`；`/clans/search` → 返回 `{"items": [...]}`（可用 `clan_detail` 造一条）；`/clans/` → `clan_detail.json`；`/locations` → `locations.json`；`/rankings/clans` → `ranking_clans.json`；其他 → `httpx.Response(404, json={"reason": "notFound"})`。均返回 `httpx.Response(200, json=<dict>)`。

- [x] **Step 4: 运行确认通过**

Run: `cd backend; python -m pytest tests/coc/test_devfixtures.py -q`
Expected: PASS。

- [x] **Step 5: 接入 `app/main.py`**（仅改 `lifespan` 里 `CocClient(...)` 构造：按 `is_placeholder_token` 传 `transport`，token 为空时传 `"PLACEHOLDER"`）。

- [x] **Step 6: 回归 + Commit**

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

- [x] **Step 1: 写失败测试 `tests/test_devseed.py`**

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

- [x] **Step 2: 运行确认失败**

Run: `cd backend; python -m pytest tests/test_devseed.py -q`
Expected: FAIL（`ModuleNotFoundError: app.devseed`）。

- [x] **Step 3: 实现 `app/devseed.py`**：读 `locations.json` → `Location(id, name, is_country, country_code)` 列表 → `upsert_all(session, Location, rows, "id")`；读 `ranking_clans.json` 的 `items` → `await replace_rankings(session, RankingKind.clans, location_id, None, None, items)`；`location_id` 缺省用 `32000001`；`await session.commit()`。

- [x] **Step 4: 运行确认通过**

Run: `cd backend; python -m pytest tests/test_devseed.py -q`
Expected: PASS。

- [x] **Step 5: 给 `app/cli.py` 加子命令**：`seed-dev-rankings`（参数 `--location` 默认 `32000001`），`main()` 里 `asyncio.run` 调 `seed_dev_rankings`（自建 session，参照 `_import_with_own_session` 的写法），打印 `counts`。

- [x] **Step 6: 验证 CLI + Commit**

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

- [x] **Step 1: 初始化工程**（`npm create vite@latest frontend -- --template vue-ts`），装依赖：

```bash
cd frontend
npm i vue-router pinia element-plus axios
npm i -D vitest @vue/test-utils jsdom @vitejs/plugin-vue typescript
```

- [x] **Step 2: 配置 `vite.config.ts`**：`plugins:[vue()]`；`server.proxy = { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } }`；`test: { environment: 'jsdom', globals: true }`；`package.json` 脚本加 `"test": "vitest run"`。

- [x] **Step 3: 写失败测试 `src/layouts/MainLayout.spec.ts`**

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

- [x] **Step 4: 运行确认失败**：Run `cd frontend; npm run test` → FAIL。

- [x] **Step 5: 实现 `MainLayout.vue`**（Element Plus `el-container` + `el-aside`（`el-menu` 两项）+ `el-main` 内 `<router-view/>`）、`router/index.ts`（上述 4 条路由，先指向占位组件，Task 7/8 替换）、`main.ts`（挂 `router`、`pinia`、`ElementPlus`、`styles/main.css`）。

- [x] **Step 6: 运行确认通过 + 构建**

Run: `cd frontend; npm run test; npm run build`
Expected: 测试 PASS，`build` 产出 `dist/`。

- [x] **Step 7: Commit**

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

- [x] **Step 1: 写失败测试 `src/api/request.spec.ts`**（用 `axios-mock-adapter` 或直接 `vi.mock('axios')`；以下断言是契约核心）

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

- [x] **Step 2: 运行确认失败**：Run `cd frontend; npm run test` → FAIL。

- [x] **Step 3: 实现 `request.ts`/`types.ts`**：axios 实例 `baseURL: import.meta.env.VITE_API_BASE || ''`；成功分支**先**判 body 是非 null 非数组对象、再判 `meta != null`，否则 `throw new ApiError('BAD_RESPONSE', ..., status)`；`toCamelMeta` 用 `=== undefined ? null : v`（**不可**用 `v || null`）；错误分支优先透传 `body.error.code`（须为非空字符串），否则按 status 归一；catch 网络错误 → `ApiError('NETWORK_ERROR', ..., 0)`。**不特判 STALE。**

- [x] **Step 4: 运行确认通过**：Run `cd frontend; npm run test` → PASS。

- [x] **Step 5: Commit**

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

- [x] **Step 1: 写失败测试 `src/utils/format.spec.ts`**

```ts
// formatNumber: null/undefined/NaN/boolean/'' -> '-'; 12345 -> '12,345'
// 大数防科学计数法: formatNumber(1e21) -> '1,000,000,000,000,000,000,000'
// formatCompact: 12345 -> '1.2万'; 1.5e8 -> '1.5亿'; 9999 -> '9,999'
// formatCompact(3e29) 不得塌成 '3亿'（数量级必须保住）
// normalizeTag: '＃8qu8j9j' -> '#8QU8J9J'; 'abc' -> null; '' -> null
// formatRelativeTime: now-30s -> '刚刚'; 未来时间 -> '刚刚'
```

- [x] **Step 2: 运行确认失败**：Run `cd frontend; npm run test` → FAIL。

- [x] **Step 3: 实现 `format.ts`**：逐函数移植 `..\COC\utils\format.js` 的算法（`toFiniteNumber`、`expandExponential`、`groupThousands`、`oneDecimal` 的两分支去尾零、`TAG_RE=/^[0-9A-Z]{3,10}$/`、`ENUM_LABELS` 表），加 TS 类型。

- [x] **Step 4: 运行确认通过**：Run `cd frontend; npm run test` → PASS。

- [x] **Step 5: Commit**

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

- [x] **Step 1: 写失败测试 `src/components/TagInput.spec.ts`**

```ts
// 输入 '＃8qu8j9j' 点查询 -> emit('submit', '#8QU8J9J')
// 输入 'abc' -> 不 emit，显示校验提示（不构造注定 400 的请求）
```

- [x] **Step 2: 写失败测试 `src/pages/PlayerDetail.spec.ts`**（mock `endpoints.ts`）

```ts
// 成功: 渲染 name/tag；带上 meta.cache
// STALE: cache==='STALE' 时仍渲染档案，并出现「数据可能过期」文案（不是错误卡片）
// 404 PLAYER_NOT_FOUND: 渲染 ErrorCard 且文案含「玩家不存在」
// BAD_RESPONSE: 渲染 ErrorCard（不白屏）
```

- [x] **Step 3: 运行确认失败**：Run `cd frontend; npm run test` → FAIL。

- [x] **Step 4: 实现**：`endpoints.ts`（typed 调用，tag 用 `encodeURIComponent`）；`TagInput.vue`（用 `normalizeTag` 校验后 `emit('submit', tag)`）；`ErrorCard.vue`（按 `ApiError.code` 给中文文案 + 重试按钮）；玩家详情用 `el-descriptions` + `formatNumber`；部落详情同构（可复用 `StatGrid.vue`）；`router/index.ts` 接真实页面。

- [x] **Step 5: 运行确认通过 + 构建**：Run `cd frontend; npm run test; npm run build` → PASS。

- [x] **Step 6: Commit**

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

- [x] **Step 1: 写失败测试 `src/pages/Rankings.spec.ts`**（mock `endpoints.ts`）

```ts
// 初始加载地区列表，默认选中夹具中的国家地区（如 China/32000001）
// 切换 kind 触发重新拉取，表格渲染 name/rank/trophies
// 空 items -> 显示「暂无数据」空态（不是错误）
// page_size 传 100（>50）-> 不报错；表格按后端返回渲染（后端会截断为 50）
```

- [x] **Step 2: 运行确认失败**：Run `cd frontend; npm run test` → FAIL。

- [x] **Step 3: 实现 `Rankings.vue` + `RankingTable.vue`**：`el-select`（地区）+ `el-radio-group`（榜单类型）+ `el-table` + `el-pagination`（`page-size` 默认 20，最大 50）。

- [x] **Step 4: 运行确认通过 + 构建**：Run `cd frontend; npm run test; npm run build` → PASS。

- [x] **Step 5: Commit**

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

- [x] **Step 1: 起三项**（分别后台起）

```powershell
C:\pgportable\pgsql\bin\pg_isready.exe -h 127.0.0.1 -p 5433 -U postgres   # PG 就绪
cd backend; Copy-Item .env.example .env   # 若尚未建；DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:5433/postgres，COC_API_TOKEN 留空
cd backend; python -m app.cli seed-dev-rankings
cd backend; python -m uvicorn app.main:app --reload --port 8000
cd frontend; npm run dev
```

- [x] **Step 2: 后端自检**

Run: `curl.exe http://127.0.0.1:8000/healthz`；`curl.exe "http://127.0.0.1:8000/api/v1/players/%239QJ8L0"`
Expected: 200；玩家 payload 的 `data.tag` 形如 `#...`，`meta.cache` ∈ {MISS,HIT}。

- [x] **Step 3: 浏览器手测**（`http://localhost:5173`）—— **已补做通过**（2026-10-17）。首次被系统级 AdGuard 阻断（子资源 502、`#app` 为空），重跑时该拦截未再出现，逐项实测如下：

| 手测项 | 结果 |
| --- | --- |
| 首页渲染 | 侧边栏只有「查询」「排行榜」；标题 `查询 · COC 助手` |
| 点快捷链接 `#9QJ8L0（玩家）` | 跳 `/players/%239QJ8L0`，渲染 Vasilije / 等级 205 / 奖杯 **4,902**（千分位生效）/ 大本营 16 / 部落角色 首领 |
| 输入框输入 `8qu8j9j` + **回车** | `normalizeTag` 补 `#` 并转大写 → 跳 `/players/%238QU8J9J`，`GET /api/v1/players/%238QU8J9J` 返回 **200**（Vite `/api` 代理链路通） |
| 输入 `ab` + 回车 | **就地提示**「标签格式不对：应为 3-10 位字母数字（如 #8QU8J9J）」，URL 不变（不构造注定 400 的请求） |
| 部落详情 `/clans/%232PP` | Reddit Zulu / 部落等级 18 / 部落积分 **55,406** / 成员 44 / 战争胜场 402 / 开战频率 始终开战 |
| 排行榜 | 表格 3 行（Reddit Zulu #2PP、Sinai #8QU8J9J、Nova China #9GP0CV9）、`Total 3`、菜单高亮「排行榜」 |
| 手改地址 `/no-such-page` | 404 兜底页：显示该地址 + 「回到查询」按钮，**不是空白 router-view** |
| 同一资源二次加载 | `meta.cache` 由 `MISS` 变 **`HIT`**（见下方第 3 处缺陷） |

顺带补的收尾（见 `ee9884a`）：`index.html` 的 `lang=en`/`title=frontend` 脚手架残留、路由级
`document.title`、404 兜底页、品牌 favicon、`frontend/README.md`。

- [x] **Step 4: 记录 + Commit**

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

- [x] **Step 1: 写 `frontend/Dockerfile`**（多阶段）

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

- [x] **Step 2: 写 `deploy/nginx.conf`（HTTP-only，默认）**：`location / { root /usr/share/nginx/html; try_files $uri $uri/ /index.html; }`；`location /api/ { proxy_pass http://api:8000; }`；`/admin/`、`/media/`（alias + `autoindex off`）、`/healthz`、`/readyz`（`access_log off`）；**透传 `X-Forwarded-For`**；文件末尾保留注释版 `443 ssl` server 段作为 HTTPS 开关参考。

- [x] **Step 3: 写根 `docker-compose.yml`**：`postgres`（`postgres:16-alpine`，卷 `pgdata`，healthcheck `pg_isready`）；`api`（`build: ./backend`，`depends_on` postgres healthy，环境同 COCBack 的 `api`，`APP_ROLE=all`）；`web`（`build: ./frontend`，`ports: ["80:80"]`，挂载 `./deploy/nginx.conf:/etc/nginx/conf.d/default.conf:ro`，`depends_on: [api]`）。**只有 web 映射端口。**

- [x] **Step 4: 写根 `.env.example`**：`POSTGRES_DB/POSTGRES_USER/POSTGRES_PASSWORD/COC_API_TOKEN/COC_BASE_URL/APP_ROLE/ADMIN_USERNAME/ADMIN_PASSWORD/ADMIN_SECRET_KEY/PUBLIC_BASE_URL/RATE_LIMIT_PER_MINUTE` 占位（值留空）。

- [ ] **Step 5: 校验** —— ⚠️ **本机改用静态校验代替**：Docker 不可用，跑不了 `docker compose config`；改用一个临时 Python 脚本做 69 项结构断言（服务集合、仅 web 暴露端口、卷与挂载、变量插值、nginx location 齐备等），全过。

Run: `docker compose config`（本机若 Docker 不可用，逐行人工核对服务名/卷/端口/环境变量）
Expected: 配置无语法错误，服务为 `postgres`/`api`/`web`。

- [x] **Step 6: Commit**

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

- [x] **Step 1: 写根 `README.md`**：项目简介；结构（`backend/`、`frontend/`、`deploy/`）；**本地开发**（起 PG → 后端 `.env` + `seed-dev-rankings` + uvicorn → 前端 `npm i && npm run dev` → 浏览器 `:5173`）；**构建**（`npm run build`、`pytest`）；**部署**（`cp .env.example .env` 填必填项 → `docker compose up -d --build`）；HTTPS 开关说明；夹具数据说明（`_source`/`_todo`）。

- [x] **Step 2: 更新根 `AGENTS.md`**：把「待补充」替换为真实命令与结构；保留「每次修改及时提交本地 git」；补后端硬约束引用（指向 `backend/AGENTS.md`）与前端命令。

- [x] **Step 3: 校验链接与命令**：按 README 逐条命令核对路径存在（不实际起 Docker）。

- [x] **Step 4: Commit**

```bash
git add README.md AGENTS.md
git commit -m "docs: 补齐开发/构建/部署说明并更新 AGENTS.md"
```

---

## 联调记录

**日期**：2026-10-16 / 17（本机 Windows）。**结论**：后端 HTTP 端到端**通过**；前端组件测试与生产构建通过，**浏览器 DOM 手测也已补做通过**（Task 9 Step 3），而且正是那次手测揪出了一处缓存缺陷并修掉（见下「三处后端潜伏缺陷」第 3 条）。**只剩 `docker compose up` 从未在本机跑过**（见「未完成项」）。

### 起服务（本机 Windows）

```powershell
# 1) 本地 PG（免安装，非 Docker）
C:\pgportable\pgsql\bin\pg_isready.exe -h 127.0.0.1 -p 5433 -U postgres

# 2) 后端：.env 里 COC_API_TOKEN 留空 → 自动启用 dev 夹具上游
cd backend; python -m app.cli seed-dev-rankings          # 已灌入：{'locations': 4, 'rankings': 3}
cd backend; python -m uvicorn app.main:app --port 8000

# 3) 前端开发服务器（/api 反代到 :8000）
cd frontend; npm run dev                                  # http://localhost:5173
```

### 通过项（后端自检，逐条实测）

| 检查 | 结果 |
| --- | --- |
| `GET /healthz` | 200 `{"status":"ok"}` |
| `GET /readyz` | 200 `{"status":"ready"}` |
| `GET /api/v1/players/%239QJ8L0` | 200，`data.tag=#9QJ8L0`、`name=Vasilije`、`trophies=4902`，`meta.cache=MISS` |
| 同上，紧接第二次 | 200，`meta.cache=**HIT**`、`age_seconds=0`（修复前恒为 MISS，见第 3 处缺陷） |
| `GET /api/v1/clans/%232PP` 两次 | 200 / 200，`MISS` → **`HIT`** |
| `GET /api/v1/clans/%232PP/members`、`/currentwar` 各两次 | 200，第二次均 **`HIT`** |
| 浏览器手测（`:5173`，真实点击 + 真实按键） | 见 Task 9 Step 3 的 8 项表格，全过 |
| `GET /api/v1/clans/%232PP` | 200，`data.name=Reddit Zulu`、`members=44` |
| `GET /api/v1/locations` | 200，`total=2`，首个为 `China(32000001)` |
| `GET /api/v1/rankings/clans?locationId=32000001` | 200，`total=3`，`meta.cache=HIT`（种子数据） |
| `GET /api/v1/rankings/clans?locationId=32000001&page_size=500` | **200**（按约定截断为 50，不是 422） |
| `GET /api/v1/players/ab` | 400，错误体 `{"error":{"code":"INVALID_TAG","message":...,"upstream_reason":null}}` |
| 经 Vite(5173) 反代 `/api/v1/locations` | 200，信封与直连一致（证明 `/api` 代理链路通） |
| `vite preview`(4173) 产物 | `index.html` 944B、入口 bundle 1,010,682B、经其反代 `/api/v1/rankings/clans` 200 |
| 前端测试 `npm run test` | **36 passed**（信封/错误码/STALE/tag 归一化/大数防塌/榜单切换/空态/page_size>50/路由标题/404 兜底页） |
| 前端构建 `npm run build` | exit 0 |

### 联调中发现并修复的三处后端潜伏缺陷

测试全绿并不等于「跑起来是好的」——这三处都只有**真实进程 / 真实浏览器**才会暴露：

1. **`uvicorn app.main:app` 根本起不来**。文档与 `backend/Dockerfile` 的 `CMD` 都写这个入口，
   但 `app/main.py` 只有 `create_app()` 工厂、**从无模块级 `app`**。测试只调 `create_app()`，
   Docker 又从未在本机跑过（后端 AGENTS.md 的 A2/B2 欠账），所以一直没暴露。
   → 在 `app/main.py` 末尾补 `app = create_app()`。
2. **每次请求都往日志里扔一条 `IllegalStateChangeError`**。5 处 `anext(get_session())`
   取出 session 后路由又自行 `close()`，那个 async generator 永远不会被关闭，
   垃圾回收时对已关闭的 session 再关一次。
   → `app/db/session.py` 新增 `new_session()`（直接产出 `AsyncSession`，调用方负责 close），
   替换 `_common.py` / `rankings.py` / `content.py` / `submissions.py` / `upgrade.py` 五处。
   修后重启，6 个真实请求全 200，日志中该异常计数 **0**；全量 494 测试仍全绿。
3. **详情路由的读时缓存永不命中 —— TTL 形同虚设**（浏览器手测时发现：同一部落刷两次，
   「缓存状态」一直是 `MISS`）。`app/cache/readthrough.py` 取新鲜度用的是
   `getattr(value, "fetched_at", None)`（只认**属性**），而六个真实 loader 返回的是一层
   **dict**：`{"_row": ..., "fetched_at": ...}`（clans / players / currentwar / cwl）与
   `{"_items": ..., "_fetched_at": ...}`（members / warlog）。dict 没有那个属性 → 新鲜度
   恒被当成「无从判断」→ **每个详情请求都判过期、都回源**，`meta.cache` 永远是 `MISS`。
   真实 Token 下等于每个详情/成员/战报请求都白打一次官方（走 RoyaleAPI 免费代理时还白挤
   共享配额），而库里明明躺着 300s / 120s TTL 内的新鲜数据。
   **为什么 494 个测试全绿仍是漏网**：单元测试的 loader 返回的是 **ORM 行对象**（属性形状），
   与生产的 dict 形状不是一回事；API 层断言又只写 `cache in {"HIT", "MISS"}`，正好放过 MISS。
   → `_fetched_at_of` 改为同时认 `Mapping`（键 `fetched_at` 与 `_fetched_at`）；新增 7 条测试
   （3 条单元：两种 dict 形状必须 HIT + 没有新鲜度键时仍须回源；4 条 API：clans / players /
   members / currentwar 的第二次请求必须 `HIT` 且不再回源）。
   **裁定**：`test_warlog.py::test_currentwar_not_in_war_does_not_degrade` 的前提被此修复推翻
   —— 它原先靠「缓存永远 MISS」才拿到 404，现在 TTL(120s) 内的行会合法 HIT 并返回 200。
   该用例改为先把行时间戳推到 TTL 之外再断言 404（与 warlog 那条孪生用例同构），并新增一条
   `currentwar` HIT 用例，把「命中缓存会在 TTL 内暂时掩盖 `NotInWar`」写成**显式契约**
   —— 这是缓存的本义，不是降级。修后 494 → **501 passed**，HTTP 复验四项均 `MISS` → `HIT`。

### 未完成项（本机环境阻断，非代码问题）

- **`docker compose up` 从未在本机跑过**：本机 CPU 虚拟化在固件层关闭，Docker Desktop / WSL2
  都不可用（见 Task 10 Step 5），部署资产只做到静态校验（69 项结构断言）。**第一次真实 `up`
  必须在 Linux 机器上做**：`cp .env.example .env`（填 `POSTGRES_PASSWORD` / `ADMIN_*` /
  `PUBLIC_BASE_URL`）→ `docker compose up -d --build` → `docker compose exec api alembic upgrade head`
  → `python -m app.cli import-game-data`（应产出 2073 行）→ 可选 `seed-dev-rankings`。
- ~~**浏览器 DOM 冒烟未做**~~ → **已补做通过**（2026-10-17，见 Task 9 Step 3 的 8 项表格）。
  首次被阻断的原因仍是有用信息，记在这里以免下次误判成代码问题：本机桌面浏览器被**系统级
  AdGuard** 过滤（`local.adguard.org`），它会往页面注入脚本，并对模块请求返回
  **502 Bad Gateway** / `ERR_INCOMPLETE_CHUNKED_ENCODING`，于是 `#app` 始终为空；
  同一批静态资源用 curl 取却是完整的（入口 bundle 1,010,682B，未截断）——是环境不是代码。
  另外本机还有两个**与 AdGuard 无关**的坑：`vite` 只监听 IPv6 回环，`127.0.0.1:5173`
  连不上，浏览器要用 **`http://localhost:5173`**；`Invoke-WebRequest` 会走系统代理被 AdGuard
  拦，探活请用 `curl.exe --noproxy '*'`。
- **夹具上游对任意 `/players/*` 都返回同一份样本**，所以本地**无法**触发
  「玩家不存在（404）」的真实路径；该分支由组件测试（mock）覆盖。

## Task 13：部署文档（2026-10-19）

**交付**：根目录新增 `docs/deployment.md`（定位=部署权威文档）。README、AGENTS.md 同步
挂指针；`backend/docs/deployment.md`（COCBack 小程序版遗留）顶部加过时横幅。

**关键裁定**：

1. **`backend/docs/deployment.md` 不重写、只加横幅**。它与 COCPersonal 部署资产存在
   四处实质冲突（小程序合法域名步骤 / `certbot` 服务与 `nginx` 服务名 /
   `PUBLIC_BASE_URL` 是否带协议 / `/opt/coc` 路径），照抄会踩坑；其运维脚本思路
   （certbot webroot 续期、备份清理）仍被新文档引用。
2. **两处部署脚本的处置**：`backend/deploy/backup.sh` 原样在
   COCPersonal 上会失败——① 媒体卷名硬编码 COCBack 的 `coc-backend_media`（本仓库
   compose 项目名 `cocpersonal` → 实际卷 `cocpersonal_media`）；② 脚本假设 cwd 在仓库根
   （cron 调用时 cwd 是 `$HOME`，`docker compose` 会找不到 compose 文件）。→
   改为自 `cd` 到脚本位置的上两级 + `MEDIA_VOLUME` 可覆盖；`bash -n` 校验。
   `certbot-renew.sh` **不动**（引用不存在的 `certbot`/`nginx` 服务，仅当遗留思路参考，
   新文档 §9 给出本仓库等价做法）。
3. **文档里所有数字都要能复现**，写作前实测：迁移链单 head `d4c8a36b19e6`；
   public schema 表数 **28**（27 张业务表 + alembic_version，旧文档的"27 张表"与之
   自洽）；`upgrade_items` 导入 **2073** 行（equipment 850 / troop 599 / hero 513 /
   spell 111，本机 `import-game-data` 重跑实测）；seed 幂等全量替换；采集调度
   rankings 每 6h（:13）、leagues/seasons 每 1h（:41/:29）、static_data 每天 03:17 UTC
   （全部错开整点）。
4. **诚实分级是本文的第一设计**：所有命令分 **【已验证】**（本机同代码路径实跑）与
   **【首跑核对】**（compose 从未在本机 up 过，首次部署按 §10 10 项清单逐条核对回填）。
   不假装文档=已验证的部署。
5. README「已知限制」同步收口：浏览器 DOM 冒烟已补做通过（此前那条欠账已出账），
   未完成项只剩 `docker compose up`。

## Task 14：首次真实部署的排障（2026-10-20）

**触发**：用户在一台 Linux 服务器上首次 `docker compose up` → `api` 容器 `Restarting (1)`
（web/postgres 正常）。`docker compose ps` 同时刷 4 条 `The "i6JEk" variable is not set`。

**根因（两个独立问题）**：

1. **api 崩溃 = 生产镜像缺 `itsdangerous`**。traceback：
   `main.py:151 build_admin → sqladmin/authentication.py:21 → starlette/middleware/sessions.py:8
   → ModuleNotFoundError` → uvicorn 加载 ASGI 应用失败、**exit 1** → 无限重启。
   `itsdangerous` 只挂在 `fastapi` 的 `extra == "all"` 与 `sqladmin` 的 `extra == 'auth'` 下，
   而 `pip install .` **不装 extras** → 镜像里没有；本机环境恰好装着它（`Required-by:` 为空，
   是孤儿包）→ **501 个测试全绿、镜像起不来**。
2. **`${i6JEk}` 警告 = `.env` 的值被 compose 插值**。`POSTGRES_PASSWORD=:jL$i6JEk*^!`
   里的 `$i6JEk` 被当成未定义变量 → 静默截断成 `:jL*^!`。**两边同步截断**
   （`POSTGRES_PASSWORD` 与 `DATABASE_URL` 读同一个值）→ 认证仍对得上，但密码已不是设的那个。

**裁定**：

1. `itsdangerous>=2.0` **显式声明**进 `pyproject.toml`（不靠 extra 顺带）。
2. 新增守门测试 `backend/tests/test_runtime_deps.py`：把「本机装着、但不在已声明依赖闭包内」
   的孤儿包**屏蔽掉**，再在子进程里 `import app.main` —— **复现镜像环境**。
   **第一版是假测试**：闭包计算把 `extra == "..."` 的依赖也算进去了（等于假装镜像里有它们），
   于是 itsdangerous 进了闭包、没被屏蔽 → 测试在修复前就绿。修正为按 marker 求值、
   `extra=""` → extras 一律排除后，测试**先红（复现出与容器完全相同的 traceback）、
   再由 `pyproject.toml` 的声明转绿**。
3. 文档 `docs/deployment.md` §2 新增「密码里的 `$` 会被 compose 插值」小节：
   单引号=不插值、双引号也插值、无引号插值（均本机实测）；建议密码只用字母数字；
   改密码后要 `ALTER USER` 同步数据库角色。§3 补「镜像里只有声明过的依赖」的提醒。
4. `backend/AGENTS.md` 的「环境陷阱」新增同款条目（本机 vs 镜像的依赖差异）。

**排障方法沉淀**（下次同类问题可直接用）：

- `Restarting (1)` = uvicorn **导入期**失败（`load_app` 抛异常 → exit 1），不是运行期错误；
- compose 的 `${VAR:?}` 检查的是**插值后**的值 → 必填变量不可能为空；
- `Settings` 的必填字段拿到**空串不报错**（pydantic 合法）→ 「配置缺失」可排除；
- 两者合起来把嫌疑范围压到「镜像缺依赖」与「代码版本过旧」两项，再用日志 traceback 一眼分辨。

**验证**：503 passed（501 + 2 条新守卫）；构建出的 wheel 元数据含
`Requires-Dist: itsdangerous>=2.0` → 镜像的 `pip install .` 会装上它。

**欠账**：本机无 Docker，真实 `up` 在服务器侧验证。

### Task 14 续：首次真实 `up` 的结果（2026-10-20，Linux 服务器）

修复推送后，服务器 `docker compose up -d --build`：

- 两个镜像构建完成（api 的 `pip install .` 耗时 **22 分钟**——PyPI 带宽慢；web 的
  `npm ci` + `npm run build` 合计约 20 秒）；
- `docker compose ps`：**api `Up (healthy)`**（此前是 `Restarting (1)`）、
  postgres healthy、web `0.0.0.0:80->80/tcp`；api 只暴露 `8000/tcp`、**未映射到宿主机**
  ✓（符合「只有 web 对外」的规矩）；
- `alembic upgrade head` 跑完 9 个迁移 → `alembic current` = **`d4c8a36b19e6 (head)`**
  ✓（与本机测得的 head 一致）；public schema 表数 **28** ✓（27 业务表 + alembic_version）；
- **第 6–12 项（导入升级数据、冒烟、后台登录、镜像依赖抽查、`.env` 插值检查）当时未执行**，
  密码轮换也还没做 → `i6JEk` 警告仍在（等值截断后的 `:jL*^!` 仍在用）。

**顺带观察（未处理）**：builder 阶段 `PIP_NO_CACHE_DIR=1` → 每次重建都重下全部依赖，
22 分钟基本都耗在这；用 BuildKit cache mount 可显著缩短。`Docker Compose is configured to
build using Bake, but buildx isn't installed` 是无害告警（compose 内置 bake 兜住了构建）。

## Task 15：夹具没随包分发（2026-10-20）

**触发**：服务器上 `docker compose exec api python -m app.cli seed-dev-rankings` 报
`FileNotFoundError: .../site-packages/tests/fixtures/locations.json`。

**根因（比报错大得多）**：夹具放在 `backend/tests/fixtures/`（**测试专用目录**），
但它们是**运行时资产**：

- `app/coc/devfixtures.py` 的 `FixtureTransport`（无 Token 时的上游替身）在**请求时**读夹具；
- `app/devseed.py`（灌排行种子）在**运行时**读夹具。

两者都用仓库相对路径（`parents[N] / "tests" / "fixtures"`）定位，而生产镜像是
`pip install .` 装进 site-packages 的 —— **`tests/` 根本不进镜像**，
镜像里解析出来是 `site-packages/tests/fixtures`（不存在）。

所以：**无 Token 的部署里，所有上游读取接口（玩家/部落/地区）全部 500**，
不止 seed 命令坏。这条与 Task 14 是同一类缺陷（**本机能跑 ≠ 镜像能跑**），
只是这次坏在「数据文件」而不是「Python 包」。

**裁定**：

1. **夹具搬进包内**：`backend/tests/fixtures/*.json` → `backend/app/coc/fixtures/`
   （5 份，含只给测试用的 `coc_units_mini.json`）。理由：夹具是运行时资产，
   放 `tests/` 下注定进不了镜像。历史规格/计划里写的 `tests/fixtures/` 保持原样
   （那是当时的记录），**以本次裁定为准**。
2. **路径唯一定义**：`devfixtures.FIXTURES_DIR = Path(__file__).parent / "fixtures"`；
   `devseed` 不再自己算路径，直接 `from app.coc.devfixtures import FIXTURES_DIR`。
3. **`pyproject.toml` 声明 package-data**（`"app.coc" = ["fixtures/*.json"]`）——
   不声明则 wheel 里没有 JSON，源码树里跑得通、装出来照样 FileNotFoundError。
4. 测试跟着改：`tests/fixtures/test_samples.py` → `tests/test_fixture_samples.py`；
   `test_mappers.py` 与 `test_game_data.py` 改用包内路径（后者原来是 cwd 相对路径，
   换个目录就断）。
5. 守门测试 `tests/test_runtime_deps.py::test_fixtures_are_packaged_with_the_app`：
   夹具必须在包目录下 + 文件齐全 + `package-data` 必须声明。

**验证**：504 passed（503 + 1 条新守卫）；构建 wheel 后确认
`app/coc/fixtures/*.json` **在包内**；再把 wheel `--no-deps --target` 装进临时目录、
**在没有 `tests/` 的条件下**跑夹具上游 → 玩家 200 `#9QJ8L0`、地区 200 共 4 条、
部落 200 `#2PP`、`devseed` 读到 3 条榜单（修复前这些全是 FileNotFoundError）。

**顺带修掉守卫自身的误报**：依赖守卫一度把应用自己（`app`）当成「未声明的孤儿包」
屏蔽了 —— 源码树里任何 `*.egg-info` 构建残留都会让 `packages_distributions()`
把 `app` 映射到本项目发行包。修正：**项目自身算「镜像的一部分」**，纳入声明集。

**教训（两条同源）**：

- 「本机测试全绿」不等于「镜像能跑」。镜像里只有 `pyproject.toml` 声明过的**包**与
  **package-data**，仓库里的其他文件（`tests/`、脚本、配置）统统不在。
- 因此凡是要在**运行时**被读到的文件，都必须**随包分发**，并有测试守着。

## Task 16：镜像构建提速（2026-10-20）

**问题**：首次真实 `up` 时 api 镜像构建耗时 **22 分钟**，几乎全在 `pip install .` 的下载上
（服务器到 PyPI 带宽很慢）。之后每次改代码重建都要再等一遍。

**根因**：`backend/Dockerfile` 的 builder 层设了 `PIP_NO_CACHE_DIR=1` —— 它把 pip 的
下载缓存整个关掉，于是**每次构建都从零下载全部依赖**。

**处置**：

1. 删掉 `PIP_NO_CACHE_DIR=1`（保留 `PIP_DISABLE_PIP_VERSION_CHECK=1`）。
2. 给装依赖的 `RUN` 挂 BuildKit cache mount：
   `--mount=type=cache,target=/root/.cache/pip` —— 下载缓存留在 BuildKit 缓存里，
   **不进镜像层**（不影响产物内容与可复现性）。
3. 守门测试加进 `backend/tests/test_deployment_config.py`：
   - `test_dockerfile_does_not_disable_pip_cache`：不许再出现 `PIP_NO_CACHE_DIR=1`
     （按本文件既有风格，**先滤掉注释行**再匹配 —— 第一版把注释里那句解释也匹配上了，
     测试当场变红）；
   - `test_dockerfile_uses_buildkit_cache_mount_for_pip`：cache mount 必须挂上。

**效果**：第一次构建仍要下全量（十几分钟），之后每次重建只花「缓存命中」的时间。
**代价**：需要 BuildKit（Docker 23+ 默认启用）。服务器上的构建日志显示走的是
BuildKit（`docker:default` 驱动 + `=>` 进度格式），所以 cache mount 可用；
若在旧 Docker 上报 `--mount option requires BuildKit`，用 `DOCKER_BUILDKIT=1` 或升级。

**验证**：506 passed（504 + 2 条新断言）；**构建加速效果需在服务器上实测**
（本机无 Docker，无法给出秒数）。

## Task 17：数据库密码冻结（2026-10-20）

**触发**：服务器上 api 容器 `unhealthy`；`seed-dev-rankings` 报
`asyncpg.exceptions.InvalidPasswordError: password authentication failed for user "coc"`。

**根因**：**postgres 角色的密码在数据卷首次初始化时就被冻结**。官方镜像只对**空**数据
目录应用 `POSTGRES_PASSWORD`；之后改 `.env` 里的密码 → compose 会重建 postgres 容器
（配置变了）→ 但库里的角色密码**不会变** → api 的 `DATABASE_URL` 用的是新值 → 认证失败。

**先排除掉的假设**：compose 对 `POSTGRES_PASSWORD` 与 `DATABASE_URL` 两处给的**是同一个值**
（本机实测：两边都是 `:jL*^!`）——所以不是 compose 插值不一致的问题，是**库里的角色密码**
与 `.env` 脱节了（期间改过 `.env` 的密码）。

**为什么 api 是 `unhealthy` 而不是干脆起不来**：健康检查用的是 `/readyz`（会连 DB），
认证失败 → 探针 503 → 标记 unhealthy。**这正是当初选 `/readyz` 而不是 `/healthz` 的价值**：
故障被探针直接暴露，而不是让流量打到 500 上。

**处置（文档化，不改代码）**：`docs/deployment.md` §2 新增「改 `.env` 里的密码 ≠ 改了数据库
的密码」小节 —— 改密码必须 `ALTER USER` + 改 `.env` + `up -d` 三步一起做；
§11 排障表加对应条目。**没有代码可改**：这是 postgres 官方镜像的既定行为，
能做的只是别让人踩。

**顺带说明**：本次同时验证了 Task 15 的修复 —— 夹具确实进了镜像
（`/opt/venv/lib/python3.12/site-packages/app/coc/fixtures`，5 份齐全）。

## Task 18：切到真实 Token 后的运维闭环（2026-10-21）

**背景**：用户在服务器上填了真实 `COC_API_TOKEN` + `COC_BASE_URL`（RoyaleAPI 代理），
后端从「夹具模式」切到「真实上游模式」。由此暴露三件事：

1. **夹具 tag 的 404 是正确行为**：`#9QJ8L0` 是手搓的假 tag，官方上不存在。
   判定「是否还在夹具模式」要看 `COC_API_TOKEN` 是否为空/字面量 `PLACEHOLDER`
   —— `app/coc/devfixtures.py::is_placeholder_token`。**注意 `/api/v1/locations`
   读的是数据库（`locations` 表 + `is_country` 过滤），不走上游**，
   所以它返回夹具数据**不能**用来判断模式。
2. **夹具种子留下的假排行必须清掉**：`seed-dev-rankings` 灌的 3 条是手搓数据，
   真实采集按 scope 全量替换，但在第一次采集成功前它们会**冒充真榜单**被吐出去
   → 部署文档 §6 增加 `DELETE FROM rankings;` 这一步。
   （`locations` 表不用清：那 4 行用的都是真实官方 id，`static_data` 采集会 upsert 补齐。）
3. **没有「立刻采一次」的命令**：调度器按 cron 触发（rankings 每 6 小时），
   刚换好 Token 最长要等 6 小时才有第一批真数据。

**处置**：

1. **新增 `python -m app.cli collect <job>`**：手动跑一次采集 job
   （`static_data` / `rankings` / `leagues` / `seasons`）。
   走的是**和调度器完全同一条路径**（`app.collector.service.run_job`）——
   同样的运行留痕、同样的部分失败记账、同样的令牌桶；手工另写一套会让两种口径分叉。
   job 名**从 `JOBS` 取**（不另抄一份名单，否则加了新 job 忘了改这里就成了
   「文档里有、命令跑不了」）。`partial` 也算失败（退出码 1），脚本里才能判。
   新增测试 `tests/test_cli_collect.py`（7 条）；同时更新既有
   `test_cli_exposes_expected_commands` 的命令集合期望（三个）。
2. **部署手册补 §7「日常运维」**（此前缺整节）：`.env` 变更规则、日志/状态、
   手动采集、备份与恢复（含 crontab）、升级发版、限流与缓存观察。
3. **章节重编号**：插入 §7 后，原 §7~§11 顺延为 §8~§12，并**同步全仓的 `§` 交叉引用**
   （`docs/deployment.md` / `AGENTS.md` / `README.md` / 本账本）。

**「改了 `.env` 要不要重启」—— 写进手册的那条规则**：

| 命令 | 新 `.env` 生效吗 |
| --- | --- |
| `docker compose up -d` | ✅ 比对解析后的配置，变了就**重建**该容器 |
| `docker compose restart` | ❌ 只重启进程，**沿用创建时的环境变量** |

原因：`.env` 是宿主机上 compose 读的，值被**注入**容器环境变量，文件本身没挂进容器。
只有**受影响的服务**会重建（只改 `COC_API_TOKEN` → 只重建 api；
改 `POSTGRES_PASSWORD` → postgres 与 api 都重建，因为 `DATABASE_URL` 是拼出来的）。

**验证**：513 passed（506 + 7 条新测试）；CLI 实测 `collect --help` 列出四个 job。

