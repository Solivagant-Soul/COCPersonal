# 阵型功能与视频导入流水线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `/bases` 从占位页做成可浏览、可上传的阵型库，并把「B 站阵型分享视频 → 30 条阵型入库」固化成可重跑的项目 skill。

**Architecture:** 后端复用既有 `base_layouts` 表，新增一个公开只读列表路由和一个管理员 multipart 上传路由；图片落 `MEDIA_ROOT` 的 `media` 卷，URL 以 `/media/` 暴露。前端重写 `/bases` 为卡片列表 + 筛选 + 上传弹窗；批量导入由 `.opencode/skills/coc-base-import/` 下的 Python 脚本完成，调用同一个上传接口。

**Tech Stack:** FastAPI、SQLAlchemy async、PostgreSQL、pytest；Vue 3、Element Plus、Vitest、axios；Python 3.12、yt-dlp、imageio-ffmpeg（自带 ffmpeg）、requests。

**Spec:** `docs/superpowers/specs/2026-11-04-coc-base-layouts-design.md`

## Global Constraints

- 后端测试一律 `cd backend && python -m pytest -q`；`asyncio_mode=auto`，异步测试**不要**加 `@pytest.mark.asyncio`
- 分页 `page_size` 上限 50，**截断为 50 并返回 200**，不得 422
- 响应信封固定 `{"data": ..., "meta": {"cache", "fetched_at", "age_seconds", "ttl_seconds"}}`，`meta.cache` 只能是大写 `HIT` / `MISS` / `STALE`
- 前端所有 URL 与查询参数名只出现在 `frontend/src/api/endpoints.ts`；页面不拼字符串
- 样式只用 `main.css` 的主题变量（`--surface-*` / `--text-*` / `--accent-gold`），不写死颜色
- 图片 ≤ 5 MiB；类型按 magic bytes 判定；存储 URL 前缀固定 `/media/bases/YYYY/MM/`
- 上传接口鉴权复用 `ADMIN_USERNAME` / `ADMIN_PASSWORD`，任一为空时一律 401
- **不新增数据库迁移**；不改 `deploy/nginx.conf`、`docker-compose.yml`
- 每完成一个任务提交一次，中文 + conventional prefix；默认不 push

## Review Focus

1. 环境变量为空时 Basic 鉴权若用 `"" == ""` 放行，等于上传接口完全公开 → Task 2 钉死「空环境变量 + 任意凭据 → 401」
2. 扩展名/Content-Type 说谎的非图片字节若直接落盘，`/media/` 会托管任意内容 → Task 2 用 magic bytes 判定并测伪装文本
3. 重跑导入若不去重，30 条会变成 60/90 条 → Task 2 测幂等，Task 10 验收里再跑一次
4. 公开列表若漏掉 `is_published` 过滤，草稿/未审内容会直接外泄 → Task 1 测「草稿不出现」
5. 没有 `layoutLink` 的条目若仍渲染复制按钮，用户会复制到 `null`/空串 → Task 5 测「无链接不渲染按钮」
6. 上传返回 401 时前端若仍提示成功，用户会以为传上去了 → Task 6 测 401 分支

---

### Task 1: 后端公开阵型列表

**Files:**
- Create: `backend/app/api/routes/bases.py`
- Modify: `backend/app/main.py`（import 元组与 `include_router`）
- Test: `backend/tests/api/test_bases.py`

**Interfaces:**
- Consumes: `app.db.models.BaseLayout`、`app.api.schemas.{DataOut, MetaOut, DEFAULT_PAGE_SIZE, clamp_page_size}`
- Produces: `base_layout_out(row: BaseLayout) -> dict[str, object]`；`GET /api/v1/bases`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/api/test_bases.py
import datetime as dt
import pytest
from app.db.models import BaseLayout


def _row(**over):
    data = dict(
        title="t", th_level=18, layout_link=None, image_path=None,
        source_url=None, source_site="bilibili", content_hash=None,
        copy_count=0, is_published=True, created_at=dt.datetime.now(dt.UTC),
    )
    data.update(over)
    return BaseLayout(**data)


async def test_list_only_published(client, session):
    session.add_all([_row(title="published"), _row(title="draft", is_published=False)])
    await session.commit()

    resp = await client.get("/api/v1/bases")

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["total"] == 1
    assert [i["title"] for i in body["data"]["items"]] == ["published"]
    assert body["meta"]["cache"] == "HIT"


async def test_list_filters_by_th_level(client, session):
    session.add_all([_row(title="18本", th_level=18), _row(title="17本", th_level=17)])
    await session.commit()

    resp = await client.get("/api/v1/bases", params={"th_level": 18})

    assert [i["thLevel"] for i in resp.json()["data"]["items"]] == [18]


async def test_list_clamps_page_size_to_50(client, session):
    session.add_all([_row(title=f"#{i}") for i in range(51)])
    await session.commit()

    resp = await client.get("/api/v1/bases", params={"page_size": 500})

    assert resp.status_code == 200
    assert len(resp.json()["data"]["items"]) == 50
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/api/test_bases.py -q`
Expected: FAIL（404 / 断言失败，路由不存在）

- [ ] **Step 3: 实现列表路由**

`backend/app/api/routes/bases.py` 顶部与签名：

```python
router = APIRouter(prefix="/api/v1")

def base_layout_out(row: BaseLayout) -> dict[str, object]:
    """单条阵型的对外形状（camelCase）。"""

async def list_bases(
    th_level: int | None = Query(default=None, ge=1, le=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1),
) -> DataOut:
```

实现要点：只查 `BaseLayout.is_published.is_(True)`；`total` 用 `select(func.count()).select_from(stmt.subquery())`；
排序 `created_at.desc(), id.desc()`；`limit` 用 `clamp_page_size(page_size)`；`meta=MetaOut(cache="HIT", fetched_at=None, age_seconds=None, ttl_seconds=0)`；
session 用 `from app.db.session import new_session` 在函数内取，`finally` 关闭。

- [ ] **Step 4: 注册路由**

`backend/app/main.py` 的 `from app.api.routes import (...)` 增加 `bases`，并在 `app.include_router(content.router)` 之前加 `app.include_router(bases.router)`。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/api/test_bases.py -q`
Expected: 3 passed

- [ ] **Step 6: 提交**

```bash
git add backend/app/api/routes/bases.py backend/app/main.py backend/tests/api/test_bases.py
git commit -m "feat: 新增阵型公开列表接口"
```

---

### Task 2: 管理员上传接口

**Files:**
- Modify: `backend/app/api/routes/bases.py`
- Test: `backend/tests/api/test_bases.py`

**Interfaces:**
- Consumes: Task 1 的 `base_layout_out`
- Produces: `POST /api/v1/admin/bases`；`check_basic_auth(header: str | None, username: str, password: str) -> bool`；`detect_image_ext(head: bytes) -> str | None`；`compute_layout_hash(title, th_level, layout_link, source_url, image: bytes) -> str`；`save_image(data: bytes, ext: str, media_root: Path, now: datetime) -> str`

- [ ] **Step 1: 写失败测试（追加到同一文件）**

```python
import base64
from sqlalchemy import func, select
from app.api.routes import bases

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
LINK = "https://link.clashofclans.com/?action=OpenLayout&id=TH18%3AWB%3Aabc"


@pytest.fixture
def admin_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "boss")
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret-pass")


@pytest.fixture
def media_root(tmp_path, monkeypatch):
    monkeypatch.setattr(bases, "_media_root", lambda: tmp_path)
    return tmp_path


async def test_upload_requires_auth(client, admin_env, media_root):
    resp = await client.post("/api/v1/admin/bases", data={"title": "x"})
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"].startswith("Basic")


async def test_upload_rejects_when_env_empty(client, monkeypatch, media_root):
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    resp = await client.post(
        "/api/v1/admin/bases", data={"title": "x"},
        headers={"Authorization": "Basic " + base64.b64encode(b":").decode()},
    )
    assert resp.status_code == 401


async def test_upload_png_publishes(client, session, admin_env, media_root):
    resp = await client.post(
        "/api/v1/admin/bases",
        data={"title": "阵型A", "th_level": "18", "layout_link": LINK},
        files={"image": ("a.png", PNG, "image/png")},
        auth=("boss", "s3cret-pass"),
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["duplicated"] is False
    assert data["imagePath"].startswith("/media/bases/")
    assert (media_root / data["imagePath"].removeprefix("/media/")).is_file()


async def test_upload_rejects_fake_image(client, admin_env, media_root):
    resp = await client.post(
        "/api/v1/admin/bases", data={"title": "x"},
        files={"image": ("a.png", b"not an image", "image/png")},
        auth=("boss", "s3cret-pass"),
    )
    assert resp.status_code == 400


async def test_upload_rejects_oversize(client, admin_env, media_root):
    big = PNG + b"0" * (5 * 1024 * 1024)
    resp = await client.post(
        "/api/v1/admin/bases", data={"title": "x"},
        files={"image": ("a.png", big, "image/png")},
        auth=("boss", "s3cret-pass"),
    )
    assert resp.status_code == 413


async def test_upload_requires_link_or_image(client, admin_env, media_root):
    resp = await client.post(
        "/api/v1/admin/bases", data={"title": "x"}, auth=("boss", "s3cret-pass")
    )
    assert resp.status_code == 400


async def test_upload_is_idempotent(client, session, admin_env, media_root):
    files = {"image": ("a.png", PNG, "image/png")}
    data = {"title": "阵型A", "th_level": "18", "layout_link": LINK}
    first = await client.post("/api/v1/admin/bases", data=data, files=files,
                              auth=("boss", "s3cret-pass"))
    second = await client.post("/api/v1/admin/bases", data=data, files=files,
                               auth=("boss", "s3cret-pass"))
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["data"]["duplicated"] is True
    count = (await session.execute(select(func.count()).select_from(BaseLayout))).scalar_one()
    assert count == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/api/test_bases.py -q`
Expected: 7 failed（路由/函数不存在）

- [ ] **Step 3: 实现鉴权、校验与落盘**

在 `bases.py` 增加模块常量与函数：

```python
MAX_IMAGE_BYTES = 5 * 1024 * 1024

def _media_root() -> Path:
    """每次调用都读 settings，测试可 monkeypatch 本函数。"""

def detect_image_ext(head: bytes) -> str | None:
    """JPEG/PNG/WebP 的 magic bytes → 扩展名；其余返回 None。"""

def check_basic_auth(header: str | None, username: str, password: str) -> bool:
    """任一凭据为空直接 False（空环境变量绝不能放行）。"""

def compute_layout_hash(title, th_level, layout_link, source_url, image: bytes) -> str:
    """sha256('v1|' + 各字段 + '|' + sha256(image).hexdigest())。"""

def save_image(data: bytes, ext: str, media_root: Path, now: dt.datetime) -> str:
    """写 {root}/bases/YYYY/MM/{uuid}.{ext}，返回 /media/bases/... 相对 URL。"""
```

`create_base(request: Request) -> JSONResponse` 要点：

1. 从 `Authorization` 头取凭据，调用 `check_basic_auth`；失败返回 401 JSON（`{"error": {"code": "UNAUTHORIZED", "message": ..., "upstream_reason": None}}`）+ `WWW-Authenticate: Basic realm="coc-admin"`，**不要 raise HTTPException**（统一错误处理器会丢掉响应头）
2. `form = await request.form()`；`title` 去空白非空且 ≤ 100
3. `th_level` 可空；`layout_link` / `source_url` 必须以 `http://` 或 `https://` 开头且 ≤ 2048
4. 图片：`await image.read(MAX_IMAGE_BYTES + 1)`；超长 → 413；`detect_image_ext(data[:12])` 为 None → 400
5. 链接与图片至少一个，否则 400（`HTTPException` + `detail={"code": "INVALID_PARAMS", "message": ...}`）
6. 先查重：`select(BaseLayout).where(BaseLayout.content_hash == h)`；命中直接返回 200 + `duplicated=True`
7. 未命中才 `save_image`，插入 `BaseLayout(..., is_published=True, source_site=form 值或 "bilibili", created_at=now UTC)`，`commit` 后返回 201 + `duplicated=False`
8. 响应体统一 `jsonable_encoder(DataOut(...))`

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/api/test_bases.py -q`
Expected: 10 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/routes/bases.py backend/tests/api/test_bases.py
git commit -m "feat: 新增阵型管理员上传接口"
```

---

### Task 3: 本地媒体服务与忽略项

**Files:**
- Modify: `backend/app/api/routes/bases.py`（`mount_media`）
- Modify: `backend/app/main.py`（调用 `mount_media`）
- Modify: `frontend/vite.config.ts`（`/media` 代理）
- Modify: `.gitignore`
- Test: `backend/tests/api/test_bases.py`

**Interfaces:**
- Produces: `mount_media(app: FastAPI, media_root: Path | None = None) -> None`

- [ ] **Step 1: 写失败测试**

```python
import httpx
from fastapi import FastAPI


async def test_mount_media_serves_existing_file(tmp_path):
    (tmp_path / "x.txt").write_text("hi", encoding="utf-8")
    app = FastAPI()
    bases.mount_media(app, tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        resp = await c.get("/media/x.txt")

    assert resp.status_code == 200 and resp.text == "hi"


async def test_mount_media_skips_missing_dir(tmp_path):
    app = FastAPI()
    bases.mount_media(app, tmp_path / "nope")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        assert (await c.get("/media/x.txt")).status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/api/test_bases.py -q -k mount_media`
Expected: FAIL（`mount_media` 不存在）

- [ ] **Step 3: 实现挂载并接线**

`mount_media`：目录存在才 `app.mount("/media", StaticFiles(directory=root), name="media")`，不存在直接返回；不要创建目录。
`main.py` 在 `app.state.admin = ...` 之前调用 `bases.mount_media(app)`。

- [ ] **Step 4: 前端加 `/media` 代理**

`frontend/vite.config.ts` 的 `server.proxy` 与 `preview.proxy` 各加：

```ts
'/media': { target: 'http://127.0.0.1:8000', changeOrigin: true },
```

- [ ] **Step 5: 忽略本地媒体与 cookie**

`.gitignore` 追加：

```gitignore
# 本地媒体与 B 站 cookie（绝不入库）
backend/.media/
.secrets/
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/api/test_bases.py -q`
Expected: 12 passed

- [ ] **Step 7: 提交**

```bash
git add backend/app/api/routes/bases.py backend/app/main.py backend/tests/api/test_bases.py frontend/vite.config.ts .gitignore
git commit -m "feat: 本地开发支持 /media 静态目录"
```

---

### Task 4: 前端 API 层

**Files:**
- Modify: `frontend/src/api/request.ts:46-50`（`RequestOptions`）与 `:97`（透传 headers）
- Modify: `frontend/src/api/endpoints.ts`（追加类型与函数）
- Test: `frontend/src/api/endpoints.spec.ts`

**Interfaces:**
- Produces:
  - `getBases(thLevel: number | null = null, page = 1, pageSize = 24): Promise<Envelope<BasesPage>>`
  - `uploadBase(input: UploadBaseInput, username: string, password: string): Promise<Envelope<BaseLayoutItem & { duplicated: boolean }>>`
  - 类型 `BaseLayoutItem`（`id`、`title`、`thLevel`、`layoutLink`、`imagePath`、`sourceUrl`、`sourceSite`、`createdAt`）、`BasesPage`（`items`、`total`）、`UploadBaseInput`（`title`、`thLevel?`、`layoutLink?`、`image?`、`sourceUrl?`、`sourceSite?`）

- [ ] **Step 1: 写失败测试**

在 `endpoints.spec.ts` 追加：

```ts
it('阵型列表固定 /api/v1/bases，参数 snake_case', async () => {
  mock.onGet('/api/v1/bases', { params: { th_level: 18, page: 1, page_size: 24 } })
    .reply(200, { data: { items: [], total: 0 }, meta: { cache: 'HIT', ttl_seconds: 0 } })
  const res = await getBases(18)
  expect(res.data.total).toBe(0)
})

it('阵型上传带 Basic 头与 multipart', async () => {
  mock.onPost('/api/v1/admin/bases').reply((config) => {
    expect(config.headers?.Authorization).toBe('Basic Ym9zczpzM2NyZXQ=')
    expect(config.data).toBeInstanceOf(FormData)
    return [201, { data: { id: 1, duplicated: false }, meta: { cache: 'MISS', ttl_seconds: 0 } }]
  })
  const file = new File([new Uint8Array([1])], 'a.png', { type: 'image/png' })
  const res = await uploadBase({ title: 'x', layoutLink: 'https://e.com', image: file }, 'boss', 's3cret')
  expect(res.data.duplicated).toBe(false)
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm run test -- endpoints.spec.ts`
Expected: FAIL（`getBases` / `uploadBase` 未定义）

- [ ] **Step 3: 实现**

`request.ts`：`RequestOptions` 加 `headers?: Record<string, string>`；`apiClient.request({ url, method, params, data, headers })`。
`endpoints.ts`：`getBases` 只在 `thLevel !== null` 时带 `th_level`；`uploadBase` 用 `FormData`（`image` 仅在 `input.image` 存在时 append），`headers: { Authorization: \`Basic ${btoa(\`${username}:${password}\`)}\` }`。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npm run test -- endpoints.spec.ts`
Expected: 全部通过（含原有 getArmies 用例）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/api/request.ts frontend/src/api/endpoints.ts frontend/src/api/endpoints.spec.ts
git commit -m "feat: 前端新增阵型列表与上传接口封装"
```

---

### Task 5: 上传表单组件

**Files:**
- Create: `frontend/src/components/BaseUploadForm.vue`
- Test: `frontend/src/components/BaseUploadForm.spec.ts`

**Interfaces:**
- Consumes: Task 4 的 `uploadBase`
- Produces: 组件 `BaseUploadForm`，无 props，emit `uploaded: []`；稳定选择器 `.upload-title`、`.upload-link`、`.upload-user`、`.upload-pass`、`.upload-submit`、`.upload-error`

- [ ] **Step 1: 写失败测试**

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/endpoints', () => ({ uploadBase: vi.fn() }))

import { uploadBase } from '../api/endpoints'
import { ApiError } from '../api/request'
import { installElementPlus } from '../plugins/element'
import BaseUploadForm from './BaseUploadForm.vue'

function mountForm() {
  return mount(BaseUploadForm, { global: { plugins: [{ install: installElementPlus }] } })
}

beforeEach(() => {
  vi.mocked(uploadBase).mockReset()
  sessionStorage.clear()
})

it('缺标题时不发请求并提示', async () => {
  const w = mountForm()
  await w.find('.upload-submit').trigger('click')
  expect(uploadBase).not.toHaveBeenCalled()
  expect(w.find('.upload-error').text()).toContain('标题')
})

it('链接和图片都缺时不发请求', async () => {
  const w = mountForm()
  await w.find('.upload-title input').setValue('阵型A')
  await w.find('.upload-submit').trigger('click')
  expect(uploadBase).not.toHaveBeenCalled()
  expect(w.find('.upload-error').text()).toContain('链接或图片')
})

it('401 提示账号密码错误且不 emit', async () => {
  vi.mocked(uploadBase).mockRejectedValue(new ApiError('UNAUTHORIZED', 'no', 401))
  const w = mountForm()
  await w.find('.upload-title input').setValue('阵型A')
  await w.find('.upload-link input').setValue('https://link.clashofclans.com/?id=a')
  await w.find('.upload-submit').trigger('click')
  await flushPromises()
  expect(w.find('.upload-error').text()).toContain('账号或密码')
  expect(w.emitted('uploaded')).toBeUndefined()
})

it('成功后 emit uploaded 并记住凭据', async () => {
  vi.mocked(uploadBase).mockResolvedValue({ data: { id: 1, duplicated: false }, meta: {} } as never)
  const w = mountForm()
  await w.find('.upload-title input').setValue('阵型A')
  await w.find('.upload-user input').setValue('boss')
  await w.find('.upload-pass input').setValue('s3cret')
  await w.find('.upload-link input').setValue('https://link.clashofclans.com/?id=a')
  await w.find('.upload-submit').trigger('click')
  await flushPromises()
  expect(w.emitted('uploaded')).toHaveLength(1)
  expect(sessionStorage.getItem('cocAdminUser')).toBe('boss')
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm run test -- BaseUploadForm.spec.ts`
Expected: FAIL（组件不存在）

- [ ] **Step 3: 实现组件**

- 字段：标题、大本等级（`el-input-number`，默认 18）、阵型链接、图片（`el-upload` `:auto-upload="false"` `:limit="1"`，`on-change` 取 `file.raw`）、来源 URL、管理员账号、口令
- 挂载时从 `sessionStorage` 读 `cocAdminUser` / `cocAdminPass`
- 提交前校验：标题非空；`layoutLink` 或 `image` 至少一个；账号/口令非空 → 错误写进 `.upload-error`
- 成功：写 `sessionStorage`、`emit('uploaded')`、清空链接/图片/标题
- `ApiError.status === 401` → `.upload-error` 文案含「账号或密码」；其它错误展示 `error.message`

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npm run test -- BaseUploadForm.spec.ts`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/BaseUploadForm.vue frontend/src/components/BaseUploadForm.spec.ts
git commit -m "feat: 新增阵型上传表单组件"
```

---

### Task 6: 阵型列表页与上传弹窗

**Files:**
- Modify: `frontend/src/pages/Bases.vue`（整体重写）
- Modify: `frontend/src/pages/Bases.spec.ts`（整体重写）

**Interfaces:**
- Consumes: Task 4 的 `getBases`、`BaseLayoutItem`；Task 5 的 `BaseUploadForm`
- Produces: `.base-card`、`.base-card__copy`、`.bases-more`、`.bases-upload` 等稳定选择器

- [ ] **Step 1: 写失败测试**

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/endpoints', () => ({ getBases: vi.fn(), uploadBase: vi.fn() }))

import { getBases } from '../api/endpoints'
import { installElementPlus } from '../plugins/element'
import Bases from './Bases.vue'

const items = [
  { id: 1, title: '#1 18本传奇防守阵', thLevel: 18, layoutLink: 'https://link.clashofclans.com/?id=a', imagePath: '/media/bases/a.jpg', sourceUrl: 'https://b23.tv/x', sourceSite: 'bilibili', createdAt: '2026-11-04T00:00:00Z' },
  { id: 2, title: '#2 国服手摆', thLevel: 18, layoutLink: null, imagePath: null, sourceUrl: null, sourceSite: 'bilibili', createdAt: '2026-11-04T00:00:00Z' },
]

function mountBases() {
  return mount(Bases, { global: { plugins: [{ install: installElementPlus }] } })
}

beforeEach(() => {
  vi.mocked(getBases).mockReset()
  vi.mocked(getBases).mockResolvedValue({
    data: { items, total: 3 },
    meta: { cache: 'HIT', fetchedAt: null, ageSeconds: null, ttlSeconds: 0 },
  } as never)
})

it('渲染阵型卡片与 TH 徽标', async () => {
  const w = mountBases()
  await flushPromises()
  expect(w.findAll('.base-card')).toHaveLength(2)
  expect(w.text()).toContain('#1 18本传奇防守阵')
  expect(w.text()).toContain('TH18')
})

it('无链接的条目不渲染复制按钮', async () => {
  const w = mountBases()
  await flushPromises()
  expect(w.findAll('.base-card__copy')).toHaveLength(1)
  expect(w.text()).toContain('国服需照图手摆')
})

it('复制按钮写入剪贴板', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
  const w = mountBases()
  await flushPromises()
  await w.find('.base-card__copy').trigger('click')
  expect(writeText).toHaveBeenCalledWith('https://link.clashofclans.com/?id=a')
})

it('加载更多请求下一页', async () => {
  const w = mountBases()
  await flushPromises()
  await w.find('.bases-more').trigger('click')
  await flushPromises()
  expect(getBases).toHaveBeenLastCalledWith(null, 2, 24)
})

it('切换等级重置到第一页并带 th_level', async () => {
  const w = mountBases()
  await flushPromises()
  w.findComponent({ name: 'ElRadioGroup' }).vm.$emit('update:modelValue', 18)
  await flushPromises()
  expect(getBases).toHaveBeenLastCalledWith(18, 1, 24)
})

it('点击上传按钮打开弹窗', async () => {
  const w = mountBases()
  await flushPromises()
  await w.find('.bases-upload').trigger('click')
  expect(w.findComponent({ name: 'ElDialog' }).props('modelValue')).toBe(true)
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm run test -- Bases.spec.ts`
Expected: FAIL（选择器/组件不匹配）

- [ ] **Step 3: 实现页面**

- `items` / `total` / `page` / `thLevel`（默认 `null`）/ `loading` / `error` / `uploadOpen`
- 页头：标题「阵型」+ `<el-radio-group v-model="thLevel">`（全部 / 17本 / 18本）+ `.bases-upload` 按钮（`@click="uploadOpen = true"`）
- 网格：`el-image`（`:src="item.imagePath"`、`:preview-src-list="[item.imagePath]"`、`lazy`）、标题、`TH{thLevel}` 徽标
- `v-if="item.layoutLink"` 才渲染 `.base-card__copy`；否则渲染 `<p class="base-card__note">国服需照图手摆</p>`
- 复制：`navigator.clipboard.writeText(link)`，失败回落 `window.open(link, '_blank')`；`ElMessage.success('已复制阵型链接')`
- 来源行：`来源：Ekwaak / Big Legends`，有 `sourceUrl` 时包一层 `<a target="_blank" rel="noopener">`
- `total > items.length` 时显示 `.bases-more`「加载更多」，点击 `page += 1` 后追加
- 切换等级：`thLevel` 变化触发 `reset()`（`page=1`、清空 items）
- `LoadingBlock` / `ErrorCard`（`@retry`）/ 空态「暂无阵型」，底部保留 `<SourceNote />`
- 上传弹窗：`<el-dialog v-model="uploadOpen" title="上传阵型"><BaseUploadForm @uploaded="onUploaded" /></el-dialog>`；`onUploaded()` 关闭弹窗、`reset()` 重载、`ElMessage.success('已上传')`

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npm run test -- Bases.spec.ts BaseUploadForm.spec.ts`
Expected: 10 passed

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/Bases.vue frontend/src/pages/Bases.spec.ts
git commit -m "feat: 阵型页改为卡片列表与等级筛选"
```

---

### Task 7: 导入脚本的纯逻辑

**Files:**
- Create: `.opencode/skills/coc-base-import/scripts/bili_links.py`
- Create: `.opencode/skills/coc-base-import/scripts/pipeline.py`（本任务只放 `frame_timestamps`）
- Create: `.opencode/skills/coc-base-import/tests/conftest.py`（把 `scripts/` 加进 `sys.path`）
- Test: `.opencode/skills/coc-base-import/tests/test_parsing.py`

**Interfaces:**
- Produces:
  - `normalize_layout_link(code: str) -> str`
  - `parse_layout_codes(text: str) -> dict[int, str]`（编号 1 起，后出现的覆盖前面的）
  - `frame_timestamps(duration: float, count: int) -> list[float]`
  - `extract_pinned_texts(payload: dict) -> list[str]`

- [ ] **Step 1: 写失败测试**

```python
from bili_links import normalize_layout_link, parse_layout_codes, extract_pinned_texts
from pipeline import frame_timestamps

CODE = "TH18:WB:AAAARAAAAAAphHQWN6eIhzQedsGoEvXp"
BASE = "https://link.clashofclans.com/?action=OpenLayout&id="


def test_parse_numbered_codes():
    text = f"1号：{CODE}\n#19：\n\nTH18:HV:AAAAMgAAAAAptjlCMeGcYAmSmerJtLYd"
    links = parse_layout_codes(text)
    assert links[1] == BASE + "TH18%3AWB%3AAAAARAAAAAAphHQWN6eIhzQedsGoEvXp"
    assert links[19] == BASE + "TH18%3AHV%3AAAAAMgAAAAAptjlCMeGcYAmSmerJtLYd"


def test_parse_ignores_plain_code_without_number():
    assert parse_layout_codes(f"好用\n{CODE}\n") == {}


def test_parse_keeps_full_url():
    full = BASE + "TH18%3AWB%3Aabc"
    assert normalize_layout_link(full) == full


def test_later_duplicate_number_wins():
    text = f"3号：TH18:WB:AAA\n3号：TH18:WB:BBB"
    assert parse_layout_codes(text)[3] == BASE + "TH18%3AWB%3ABBB"


def test_frame_timestamps_spans_duration():
    ts = frame_timestamps(91.27, 30)
    assert len(ts) == 30
    assert 0.5 < ts[0] < 0.7
    assert 88.0 < ts[-1] < 90.0


def test_extract_pinned_texts_reads_top_replies():
    payload = {"data": {"top_replies": [{"content": {"message": "笔记"}}],
                        "replies": [{"content": {"message": "普通"}}]}}
    assert extract_pinned_texts(payload) == ["笔记"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest .opencode/skills/coc-base-import/tests -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现纯函数**

- 先建 `tests/conftest.py`：`sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))`，否则测试导入不到脚本
- `normalize_layout_link`：已是 `http(s)://` 原样返回；否则 `BASE + urllib.parse.quote(code, safe="")`（冒号编码成 `%3A`）
- `parse_layout_codes`：在**整段文本**上 `re.finditer(r"(?:#|第)?\s*(\d{1,2})\s*(?:号|[:：])\s*(TH\d{1,2}:[A-Z]{2}:[A-Za-z0-9_-]+)")`，允许编号与代码之间换行；**只有匹配到编号才收录**，后出现的覆盖前面的
- `frame_timestamps`：`interval = duration / count`，返回 `[i * interval + interval * 0.2 for i in range(count)]`
- `extract_pinned_texts`：优先 `data.top_replies`，空则 `data.replies`，取 `content.message`

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest .opencode/skills/coc-base-import/tests -q`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add .opencode/skills/coc-base-import/scripts/bili_links.py .opencode/skills/coc-base-import/scripts/pipeline.py .opencode/skills/coc-base-import/tests/test_parsing.py
git commit -m "feat: 阵型导入脚本的链接与抽帧纯逻辑"
```

---

### Task 8: 流水线编排与项目 skill

**Files:**
- Create: `.opencode/skills/coc-base-import/scripts/upload.py`
- Modify: `.opencode/skills/coc-base-import/scripts/pipeline.py`
- Create: `.opencode/skills/coc-base-import/SKILL.md`
- Create: `.opencode/skills/coc-base-import/references/workflow.md`

**Interfaces:**
- Consumes: Task 7 的纯函数；Task 2 的 `POST /api/v1/admin/bases`
- Produces: `fetch_pinned(bvid: str, cookies_path: Path) -> list[str]`（wbi 签名 + cookie，返回置顶/热门评论文本）；`upload_one(image: Path, payload: dict, api_base: str, user: str, password: str) -> dict`；`python .opencode/skills/coc-base-import/scripts/pipeline.py --video-url ... --count 30 --th-level 18 --dry-run`

- [ ] **Step 1: 实现 `upload.py`**

```python
def upload_one(image: Path, payload: dict, api_base: str, user: str, password: str) -> dict:
    """POST 一条阵型；返回响应 data。非 2xx 抛 UploadError(status, message)。"""
```

用 `requests.post(f"{api_base}/api/v1/admin/bases", data=..., files={"image": (name, bytes, "image/jpeg")}, auth=(user, password), timeout=30)`；从错误体 `error.message` 取文案。

- [ ] **Step 2: 实现 `pipeline.py` 主流程**

参数：`--video-url`（必填）、`--count`（默认 30）、`--th-level`（默认 18）、`--cookies`（默认 `.secrets/bilibili-cookies.txt`）、`--links`（可选 JSON）、`--mapping`（可选 JSON）、`--api-base`（默认 `http://127.0.0.1:8000`）、`--dry-run`。

流程：`yt-dlp` 下载 720p → `ffprobe` 时长 → `frame_timestamps` → ffmpeg 逐帧导 JPEG（q=3）→ 有 `--links` 直接读，否则 `bili_links.fetch_pinned`（requests + wbi 签名 + cookie）→ 按编号组装标题 `#N {th}本传奇防守阵` → 若给了 `--mapping` 则按 `{"1": 3, "2": 1}` 重排编号 → `--dry-run` 打印表格并退出 → 逐条 `upload_one` → 汇总打印 `成功/重复/失败`，任一失败 `sys.exit(1)`。

缺链接编号：跳过上传并计入「缺链接」，退出码 1；`--dry-run` 不视为失败。

- [ ] **Step 3: 写 SKILL.md**

frontmatter：

```yaml
---
name: COC 阵型导入
description: 把 B 站阵型分享视频里的阵型（截图 + 置顶笔记链接）批量上传到 COCPersonal 站点。Use when the user gives a bilibili video link and asks to import/upload its base layouts.
---
```

正文固定五段：前置检查（cookie、`COC_ADMIN_USER` / `COC_ADMIN_PASSWORD`、`/readyz`）→ 先跑 `--dry-run` 并让人确认 → 正式上传 → 用 `GET /api/v1/bases?page_size=50` 核对 → 汇报缺号与失败。命令示例用 Task 8 的完整参数。

- [ ] **Step 4: 写 `references/workflow.md`**

内容：cookie 从浏览器导出为 Netscape 格式；置顶笔记是图片时如何手工建 `links.json`（`{"1": "https://..."}`）；`--mapping` 的格式与用途；401/403/413 的处置；重复条目如何判定。

- [ ] **Step 5: 验证**

Run: `python .opencode/skills/coc-base-import/scripts/pipeline.py --help`
Expected: 列出全部参数，退出码 0
Run: `python -m pytest .opencode/skills/coc-base-import/tests -q`
Expected: 6 passed

- [ ] **Step 6: 提交**

```bash
git add .opencode/skills/coc-base-import
git commit -m "feat: 新增阵型视频导入流水线与项目 skill"
```

---

### Task 9: 文档更新

**Files:**
- Modify: `README.md:13-15`、`README.md:56-57`
- Modify: `AGENTS.md`（「未完成的欠账」段落）
- Modify: `docs/deployment.md`（新增 §15 阵型上传与媒体目录）

**Interfaces:** 无代码接口

- [ ] **Step 1: 更新 README**

- 功能列表：「阵型（占位）」改为「阵型：18 本防守阵图集，支持站长上传链接与图片」
- 本地启动说明：阵型为占位页 → 实际页面；补一句本地需设 `MEDIA_ROOT=backend/.media`

- [ ] **Step 2: 更新 AGENTS.md**

在「未完成的欠账」加一条：阵型内容由 `coc-base-import` skill 导入，cookie 在 `.secrets/bilibili-cookies.txt`（不入库），图片在 `media` 卷。

- [ ] **Step 3: 更新 deployment.md**

新增 §15，写清：`/media` 卷的读写归属、上传接口路径与鉴权、5 MiB 限制、排障命令：

```bash
curl -s -u "$ADMIN_USERNAME:$ADMIN_PASSWORD" -F title=test -F image=@test.jpg "$PUBLIC_BASE_URL/api/v1/admin/bases"
./deploy/compose.sh exec api ls -l /data/media/bases
```

- [ ] **Step 4: 提交**

```bash
git add README.md AGENTS.md docs/deployment.md
git commit -m "docs: 补充阵型功能与媒体目录说明"
```

---

### Task 10: 全量验证与首批 30 条导入

**Files:** 无代码改动（只跑命令、必要时修 bug 并回到对应任务补测试）

**Interfaces:** 需要用户提供 `.secrets/bilibili-cookies.txt`、`COC_API_BASE`、`COC_ADMIN_USER`、`COC_ADMIN_PASSWORD`

- [ ] **Step 1: 后端全量**

Run: `cd backend && python -m pytest -q`
Expected: 全绿（原 639 + 新增 12）

- [ ] **Step 2: 前端全量 + 构建**

Run: `cd frontend && npm run test`
Expected: 全绿
Run: `cd frontend && npm run build`
Expected: 通过，无 TS 错误

- [ ] **Step 3: 本地上传冒烟**

`MEDIA_ROOT=backend/.media` 起后端与前端后：

1. 上传 1 条 → 页面出现 → 刷新仍在 → 图片能打开
2. 同一内容再传一次 → 提示重复、列表不增加

- [ ] **Step 4: 服务器导入**

```powershell
$env:COC_API_BASE="https://<站点域名>"
$env:COC_ADMIN_USER="<ADMIN_USERNAME>"
$env:COC_ADMIN_PASSWORD="<ADMIN_PASSWORD>"
python .opencode/skills/coc-base-import/scripts/pipeline.py `
  --video-url "https://www.bilibili.com/video/BV1qHpY62EoT/" --count 30 --th-level 18 --dry-run
```

先人工核对 30 行映射表，再同命令去掉 `--dry-run`。若置顶笔记解析失败，按 `references/workflow.md` 建 `links.json` 后加 `--links links.json`。

- [ ] **Step 5: 线上验收**

1. `GET /api/v1/bases?page_size=50` 返回 `total = 30`
2. 浏览器打开 `/bases`：30 张图全部加载、筛选 18 本正确、复制按钮给出现代码链接
3. 再跑一次导入 → 全部 `duplicated`，`total` 仍为 30

- [ ] **Step 6: 收尾**

若验收中修了 bug：回到对应任务补测试并按该任务的提交信息提交。全部通过且无代码改动时，不需要额外提交。
