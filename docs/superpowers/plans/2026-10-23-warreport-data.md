# War Report 数据接入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 War Report 的赛季榜（最近 3 个快照）与热门配兵接进后端采集/只读接口，并在前端加上「赛季榜 / 阵容 / 阵型占位」三个入口，按上游要求署名。

**Architecture:** 新增 `app/warreport/`（client / mappers / snapshots），由每日采集 job 写入 `rankings`（两种新 kind）与新表 `warreport_armies`；API 只读库；前端 `endpoints.ts` 是唯一知道 URL 的地方。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + PostgreSQL + Alembic；Vue 3 + TypeScript + Element Plus + Vitest；httpx。

**Spec:** `docs/superpowers/specs/2026-10-23-warreport-data-design.md`

## Global Constraints

- 后端命令一律在 `backend/` 下执行；前端命令在 `frontend/` 下执行。
- `python -m pytest -q` 全量必须全绿；前端 `npm run test` 与 `npm run build` 必须全绿。
- 异步测试**不加** `@pytest.mark.asyncio`（`asyncio_mode=auto`）；一律 `async def` + `await client.get(...)`，禁止同步 `TestClient`。
- `app/collector/` 与 `app/warreport/` **不得 import FastAPI**（`APP_ROLE=collector` 要能独立起进程）。
- 统一响应体 `{"data": ..., "meta": {...}}`，`meta.cache` 必须是**大写** `HIT` / `MISS` / `STALE`。
- 分页：`page` 默认 1，`page_size` 默认 20，**上限 50 且超限截断为 50**（不是 422）。
- SQLAlchemy 锁 `<2.1`；不新增 Python 依赖（`httpx` 已有）。
- 所有时间戳按 UTC 存 `TIMESTAMPTZ`；mapper 的 `now` 由调用方注入。
- tag 入库前统一 `app.coc.tags.normalize_tag()`，不得自行 `strip().upper()`。
- `.env` 不入库；`.env.example` 敏感项保持空值。
- War Report 署名是使用条件：页面可见 + 部署文档写明。
- 每个任务一个提交，提交信息中文 + conventional prefix（`feat:` / `fix:` / `test:` / `docs:` / `chore:`）；**只提交本地，不 push**。

## Review Focus

1. **赛季列表为空**（上游还没生成快照 / 采集没跑）→ 赛季榜必须显示「暂无赛季数据」空态，不能卡在 loading 或抛未捕获异常。（Task 8）
2. **采集时上游超时 / 5xx** → 已有的 `rankings` 与 `warreport_armies` 旧行不能被 DELETE 掉；事务必须回滚，API 继续返回旧数据。（Task 5）
3. **`?page_size=500` 与越界 `page`** → 必须 200 + 截断 / 空列表，不是 422 或 404。（Task 6）
4. **非法 snapshot / kind**（`2026-13-99`、`2026-10-5`、`foo`）→ 必须 400
   `INVALID_PARAMS`，不能 500 或打到 SQL。（Task 6）
5. **非 HTTPS / 无 clipboard 时点「复制阵型」** → 退化打开 `armyLink`，不产生未捕获的 Promise 拒绝。（Task 9）
6. **阵容响应重复 `canonicalKey` 或为空** → 整表替换要么全部成功、要么回滚保留旧数据；空响应表示「确实没有」并清空。（Task 5）

## File Structure

**后端（新增）**

| 文件 | 职责 |
|---|---|
| `backend/app/warreport/client.py` | HTTP 客户端、异常、`client_from_settings` |
| `backend/app/warreport/mappers.py` | War Report 原始 JSON → `rankings` item / `warreport_armies` row |
| `backend/app/warreport/snapshots.py` | 快照日期探测 |
| `backend/app/collector/jobs/warreport.py` | 采集 job |
| `backend/app/api/routes/warreport.py` | 赛季列表 / 赛季榜 / 阵容路由 |
| `backend/migrations/versions/0012_warreport_armies.py` | 新表 |

**后端（修改）**

`app/config.py`、`app/collector/rankings_service.py`、`app/collector/service.py`、`app/collector/scheduler.py`、`app/db/models.py`、`app/api/routes/rankings.py`、`app/main.py`。

**前端（新增）**

`src/components/SourceNote.vue`、`src/pages/Armies.vue`、`src/pages/Bases.vue`。

**前端（修改）**

`src/api/endpoints.ts`、`src/components/RankingTable.vue`、`src/pages/Rankings.vue`、`src/router/index.ts`、`src/layouts/MainLayout.vue`。

**部署/文档**

根 `.env.example`、`backend/.env.example`、`docker-compose.yml`、`backend/docker-compose.yml`、`docs/deployment.md`、`README.md`、`AGENTS.md`。

---

### Task 1: War Report 客户端与配置

**Files:**
- Create: `backend/app/warreport/__init__.py`
- Create: `backend/app/warreport/client.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/warreport/test_client.py`

**Interfaces:**
- Produces:
  - `class WarReportError(RuntimeError)`，属性 `status_code: int | None`
  - `class WarReportSnapshotNotFound(WarReportError)`
  - `class WarReportClient(base_url: str, *, timeout: float = 15.0, transport: httpx.AsyncBaseTransport | None = None)`
    - `async def get_json(self, path: str, params: dict[str, str] | None = None) -> Any`
    - `async def aclose(self) -> None`
  - `def client_from_settings(settings) -> WarReportClient`
- Consumes: 无

- [ ] **Step 1: 写失败测试**

`backend/tests/warreport/test_client.py`：

```python
import ast
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.warreport.client import (
    WarReportClient,
    WarReportError,
    WarReportSnapshotNotFound,
    client_from_settings,
)


def _client(handler) -> WarReportClient:
    return WarReportClient(
        "https://api.warreport.app/", transport=httpx.MockTransport(handler)
    )


async def test_get_json_returns_payload():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/armies"
        return httpx.Response(200, json=[{"name": "Thrower"}])

    assert await _client(handler).get_json("/armies") == [{"name": "Thrower"}]


async def test_snapshot_404_maps_to_snapshot_not_found():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "snapshot not found"})

    with pytest.raises(WarReportSnapshotNotFound):
        await _client(handler).get_json(
            "/locations/global/rankings/players", {"season": "2026-10-04"}
        )


async def test_other_4xx_maps_to_war_report_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid season"})

    with pytest.raises(WarReportError) as exc:
        await _client(handler).get_json("/armies")
    assert exc.value.status_code == 400


async def test_5xx_maps_to_war_report_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream down")

    with pytest.raises(WarReportError) as exc:
        await _client(handler).get_json("/armies")
    assert exc.value.status_code == 503


async def test_network_error_maps_to_war_report_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with pytest.raises(WarReportError):
        await _client(handler).get_json("/armies")


def test_base_url_strips_trailing_slash():
    client = WarReportClient("https://api.warreport.app/")
    assert client.base_url == "https://api.warreport.app"


def test_settings_expose_warreport_defaults():
    """直接读字段默认值，不构造 Settings。

    构造的话本机 ``backend/.env`` 里的值会盖掉默认值 —— 那是**真实配置**，
    测试不该因为开发机的 .env 而红。
    """
    assert Settings.model_fields["warreport_base_url"].default == (
        "https://api.warreport.app"
    )
    assert Settings.model_fields["warreport_timeout"].default == 15.0


async def test_client_from_settings_uses_settings():
    settings = Settings(
        coc_api_token="x",
        database_url="postgresql+asyncpg://x",
        public_base_url="http://x",
        warreport_base_url="https://fake.example/",
        warreport_timeout=3.0,
    )
    client = client_from_settings(settings)
    try:
        assert client.base_url == "https://fake.example"
    finally:
        await client.aclose()


def test_warreport_package_does_not_import_web_framework():
    """``app/warreport/`` 与 ``app/collector/`` 同级：不得依赖 Web 框架或 API 层。

    照抄 ``tests/collector/test_scheduler.py`` 的两条边界测试的写法（AST 静态查，
    不靠 import 时报错），只是把目录换成 ``app/warreport``。
    """
    offenders = []
    for path in Path("app/warreport").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in {"fastapi", "starlette", "uvicorn"}:
                        offenders.append(f"{path}:{node.lineno} import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                if root in {"fastapi", "starlette", "uvicorn"}:
                    offenders.append(f"{path}:{node.lineno} from {node.module}")
                elif node.module.startswith("app.api"):
                    offenders.append(f"{path}:{node.lineno} from {node.module}")
    assert offenders == [], "app/warreport/ 不得依赖 Web 框架或 app.api：\n" + "\n".join(
        offenders
    )
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/warreport/test_client.py -q`
Expected: FAIL（`ModuleNotFoundError: app.warreport`）

- [ ] **Step 3: 实现**

`app/config.py` 增加：

```python
warreport_base_url: str = "https://api.warreport.app"
warreport_timeout: float = 15.0
```

`app/warreport/client.py`：

```python
class WarReportError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class WarReportSnapshotNotFound(WarReportError): ...


class WarReportClient:
    def __init__(self, base_url: str, *, timeout: float = 15.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url, timeout=timeout, transport=transport
        )

    async def get_json(self, path, params=None): ...
    async def aclose(self) -> None: ...
```

`get_json` 的判定顺序：`httpx.HTTPError` → `WarReportError`；404 且 body 小写含
`snapshot not found` → `WarReportSnapshotNotFound`；其它 `>=400` →
`WarReportError(status_code=...)`；JSON 解析失败 → `WarReportError`。

`client_from_settings(settings)` 用 `settings.warreport_base_url` 与
`settings.warreport_timeout` 构造。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/warreport/test_client.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/config.py backend/app/warreport backend/tests/warreport/test_client.py
git commit -m "feat: 新增 War Report HTTP 客户端与配置"
```

---

### Task 2: War Report 数据映射

**Files:**
- Create: `backend/app/warreport/mappers.py`
- Test: `backend/tests/warreport/test_mappers.py`

**Interfaces:**
- Produces:
  - `def player_item(raw: dict) -> dict | None`
  - `def clan_item(raw: dict) -> dict | None`
  - `def army_row(raw: dict, position: int, now: dt.datetime) -> dict | None`
- Consumes: `app.coc.tags.normalize_tag`

`army_row` 要 `now`（不像前两个）：它产出的 dict 直接喂给 `WarReportArmy(**row)`，
而 `fetched_at` 是 not null 列。`player_item` / `clan_item` 不带 `now`，因为
`replace_rankings` 会自己补 `fetched_at` —— 这是既有的分工，别在 mapper 里再补一次。

产出字段必须是 `app.collector.rankings_service._row_from_item` 认识的键名：
`rank`、`previousRank`、`tag`、`name`、`clanTag`、`clanName`、`clanLevel`、
`trophies`、`expLevel`、`attackWins`、`defenseWins`、`points`、`members`。

- [ ] **Step 1: 写失败测试**

```python
import datetime as dt

from app.warreport.mappers import army_row, clan_item, player_item


def test_player_item_flattens_nested_clan_and_normalizes_tag():
    raw = {
        "tag": "#2pp", "name": "P1", "rank": 3, "previousRank": 5,
        "expLevel": 300, "trophies": 6000, "attackWins": 30, "defenseWins": 12,
        "clan": {"tag": "#c1", "name": "C1", "clanLevel": 18},
    }
    item = player_item(raw)
    assert item["tag"] == "#2PP"
    assert item["clanTag"] == "#C1"
    assert item["clanName"] == "C1"
    assert item["clanLevel"] == 18
    assert item["trophies"] == 6000
    assert item["points"] is None


def test_player_item_without_clan_is_null_safe():
    item = player_item({"tag": "#P", "name": "P", "rank": 1, "clan": None})
    assert item["clanTag"] is None


def test_clan_item_maps_clan_points_to_points():
    item = clan_item(
        {"tag": "#C", "name": "C", "rank": 1, "clanPoints": 5000,
         "members": 45, "clanLevel": 15}
    )
    assert item["points"] == 5000
    assert item["members"] == 45
    assert item["trophies"] is None


def test_mapper_drops_rows_without_rank_or_tag():
    assert player_item({"tag": "#P", "name": "P"}) is None
    assert player_item({"rank": 1, "name": "P"}) is None
    assert clan_item({"rank": 1}) is None


def test_army_row_maps_all_fields():
    now = dt.datetime(2026, 10, 23, 4, 23, tzinfo=dt.UTC)
    row = army_row(
        {"name": "Thrower", "canonicalKey": "k1", "armyShareCode": "sc",
         "armyLink": "https://link", "playerCount": 54, "useCount": 332,
         "percentage": 27.27, "averageStars": 2.73,
         "averageDestruction": 97.25},
        2,
        now,
    )
    assert row["position"] == 2
    assert row["canonical_key"] == "k1"
    assert row["average_destruction"] == 97.25
    assert row["fetched_at"] == now


def test_army_row_accepts_int_floats():
    """上游 ``averageStars``/``averageDestruction`` 有时是整数（实测有 3 与 100）。"""
    now = dt.datetime(2026, 10, 23, tzinfo=dt.UTC)
    row = army_row(
        {"name": "Balloon", "canonicalKey": "k2", "armyShareCode": "s",
         "armyLink": "https://l", "playerCount": 1, "useCount": 8,
         "percentage": 0.5, "averageStars": 3, "averageDestruction": 100},
        1,
        now,
    )
    assert row["average_stars"] == 3.0
    assert row["average_destruction"] == 100.0


def test_army_row_drops_without_canonical_key():
    now = dt.datetime(2026, 10, 23, tzinfo=dt.UTC)
    assert army_row({"name": "X"}, 1, now) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/warreport/test_mappers.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

纯函数；数值用 `int` / `float` 安全转换（`None`、字符串数字、整数都接受，转不了返回
`None`）。缺 `rank`/`name`/`tag`（玩家、部落）或 `canonicalKey`/`name`（配兵）时
返回 `None`，让采集跳过该条而不是整批失败。

`player_item` 把嵌套的 `clan` 拍平成 `clanTag` / `clanName` / `clanLevel` 三个键
（`_row_from_item` 认的是这三个扁平键名，不认嵌套对象）；`clan` 为 `null` 时三个键
都给 `None`。`clan_item` 把 `clanPoints` 映射到 `points`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/warreport/test_mappers.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/warreport/mappers.py backend/tests/warreport/test_mappers.py
git commit -m "feat: 新增 War Report 榜单与配兵映射"
```

---

### Task 3: 快照日期探测

**Files:**
- Create: `backend/app/warreport/snapshots.py`
- Test: `backend/tests/warreport/test_snapshots.py`

**Interfaces:**
- Produces:
  - 常量 `SEASON_COUNT = 3`、`SEASON_INTERVAL_DAYS = 28`、`PROBE_TOLERANCE_DAYS = 1`、`FIRST_RUN_LOOKBACK_DAYS = 35`、`FALLBACK_AFTER_DAYS = 31`
  - `async def snapshot_exists(client, day: date) -> bool`
  - `async def discover_snapshots(client, known: Sequence[str], today: date) -> list[str]`
- Consumes: `WarReportClient.get_json`、`WarReportSnapshotNotFound`

- [ ] **Step 1: 写失败测试**

```python
import datetime as dt

import pytest

from app.warreport.client import WarReportError, WarReportSnapshotNotFound
from app.warreport.snapshots import discover_snapshots, snapshot_exists


class FakeClient:
    def __init__(self, valid: set[str], error: bool = False):
        self.valid = valid
        self.error = error
        self.calls: list[str] = []

    async def get_json(self, path, params=None):
        if self.error:
            raise WarReportError("boom")
        day = params["season"]
        self.calls.append(day)
        if day not in self.valid:
            raise WarReportSnapshotNotFound("snapshot not found")
        return []


async def test_first_run_probes_backwards_and_stops_at_latest():
    today = dt.date(2026, 10, 23)
    client = FakeClient({"2026-10-05"})
    assert await discover_snapshots(client, [], today) == ["2026-10-05"]
    assert client.calls[0] == "2026-10-23"
    # 23 日到 5 日逐日 19 次；命中后再按 28 天间隔补探 09-07 那一档的 3 个候选，
    # 全不命中即停（不再往 08-10 探）
    assert len(client.calls) == 19 + 3


async def test_first_run_backfills_up_to_three_snapshots():
    """首次运行必须一次凑够 3 个赛季。

    只找到「最新一份」就停会让新部署的赛季榜只有 1 个选项，要等两个采集周期
    （约 8 周）才长到 3 个 —— 而需求就是「最近 3 个赛季」。
    """
    today = dt.date(2026, 10, 23)
    client = FakeClient({"2026-10-05", "2026-09-07", "2026-08-10"})
    assert await discover_snapshots(client, [], today) == [
        "2026-10-05",
        "2026-09-07",
        "2026-08-10",
    ]


async def test_known_dates_only_probe_three_candidates():
    today = dt.date(2026, 10, 23)
    client = FakeClient(set())  # 还没有新快照
    known = ["2026-10-05", "2026-09-07", "2026-08-10"]
    assert await discover_snapshots(client, known, today) == known
    assert client.calls == ["2026-11-02", "2026-11-01", "2026-11-03"]


async def test_new_snapshot_is_merged_and_trimmed_to_three():
    today = dt.date(2026, 11, 2)
    client = FakeClient({"2026-11-02"})
    known = ["2026-10-05", "2026-09-07", "2026-08-10"]
    assert await discover_snapshots(client, known, today) == [
        "2026-11-02", "2026-10-05", "2026-09-07",
    ]


async def test_stale_anchor_falls_back_to_backward_probe():
    today = dt.date(2026, 11, 20)
    client = FakeClient({"2026-11-16"})
    known = ["2026-10-05"]
    assert await discover_snapshots(client, known, today) == ["2026-11-16"]


async def test_snapshot_exists_returns_false_on_404():
    client = FakeClient({"2026-10-05"})
    assert await snapshot_exists(client, dt.date(2026, 10, 5)) is True
    assert await snapshot_exists(client, dt.date(2026, 10, 4)) is False


async def test_network_error_propagates():
    client = FakeClient(set(), error=True)
    with pytest.raises(WarReportError):
        await discover_snapshots(client, [], dt.date(2026, 10, 23))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/warreport/test_snapshots.py -q`
Expected: FAIL

- [ ] **Step 3: 实现**

`snapshot_exists` 调 `client.get_json("/locations/global/rankings/players/countries",
{"season": day.isoformat()})`，只吞 `WarReportSnapshotNotFound`。

`discover_snapshots` 按规格 §5.4（含 R1 裁定）：有 known 时先探 `latest+28`、`-1`、`+1`；
都不命中且 `(today - latest).days >= FALLBACK_AFTER_DAYS` 时，从 today 往前逐日
探测最多 `FIRST_RUN_LOOKBACK_DAYS` 天；无 known 时直接逐日回溯。

**命中第一份之后要继续补探**（R1）：以该日期为锚，按 `SEASON_INTERVAL_DAYS`
往前推，每档探 `候选`、`候选-1`、`候选+1`，直到凑满 `SEASON_COUNT` 份或某一档
三次全不命中为止。没有这一步，首次部署的赛季榜只有 1 个选项，要等约 8 周才长到 3 个。

回溯分支（无 known，或节奏漂移触发）**只返回补探结果，不与 known 合并** ——
锚点已经不可信时，旧的 known 可能上游早就删了，继续拉它们只会白报失败。
有 known 的正常分支才把新命中的日期合并进 known。最后去重、倒序、取前
`SEASON_COUNT` 个。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/warreport/test_snapshots.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/warreport/snapshots.py backend/tests/warreport/test_snapshots.py
git commit -m "feat: 新增 War Report 赛季快照探测"
```

---

### Task 4: 数据模型、RankingKind 与迁移 0012

**Files:**
- Modify: `backend/app/collector/rankings_service.py`（`RankingKind` 与 `_HAS_TAG`）
- Modify: `backend/app/db/models.py`（新增 `WarReportArmy`）
- Create: `backend/migrations/versions/0012_warreport_armies.py`
- Modify: `backend/tests/db/test_rankings_refresh.py`（`test_ranking_kind_covers_all_kinds` 的精确集合断言）
- Test: `backend/tests/db/test_warreport_models.py`

**Interfaces:**
- Produces:
  - `RankingKind.wr_season_players = "wr_season_players"`
  - `RankingKind.wr_season_clans = "wr_season_clans"`
  - `class WarReportArmy(Base)`，表 `warreport_armies`
- Consumes: 无

- [ ] **Step 1: 写失败测试**

```python
import datetime as dt
from datetime import UTC

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import IntegrityError

from app.collector.rankings_service import RankingKind
from app.db.models import WarReportArmy


def _row(**over):
    base = {
        "position": 1, "name": "Thrower", "canonical_key": "k1",
        "army_share_code": "sc", "army_link": "https://link",
        "player_count": 1, "use_count": 2, "percentage": 50.0,
        "average_stars": 2.5, "average_destruction": 90.0,
        "fetched_at": dt.datetime.now(UTC),
    }
    base.update(over)
    return base


async def test_warreport_armies_table_exists(session):
    exists = (
        await session.execute(text("SELECT to_regclass('warreport_armies')"))
    ).scalar_one()
    assert exists is not None


async def test_army_round_trip(session):
    session.add(WarReportArmy(**_row()))
    await session.commit()
    row = (await session.execute(select(WarReportArmy))).scalar_one()
    assert row.name == "Thrower"
    assert row.canonical_key == "k1"


async def test_canonical_key_is_unique(session):
    await session.execute(insert(WarReportArmy).values(_row()))
    with pytest.raises(IntegrityError):
        await session.execute(
            insert(WarReportArmy).values(_row(position=2))
        )
    await session.rollback()


def test_new_ranking_kinds_exist():
    assert str(RankingKind.wr_season_players) == "wr_season_players"
    assert str(RankingKind.wr_season_clans) == "wr_season_clans"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/db/test_warreport_models.py -q`
Expected: FAIL（`WarReportArmy` 不存在 / 表不存在）

- [ ] **Step 3: 实现**

`RankingKind` 增加两个成员；`_HAS_TAG` 加入两者；更新类 docstring（原文「**只有 3 类**」
改为 5 类，并补一句「赛季榜两类来自 War Report，按快照日期分 scope」）。

**同时改 `tests/db/test_rankings_refresh.py::test_ranking_kind_covers_all_kinds`** ——
它把取值集合写死成 `{"clans", "players", "season_players"}` 三个，加成员后立刻红。
改成 5 个成员，并把该测试的 docstring 从「只有 3 类」更新为「3 类官方榜 + 2 类
War Report 赛季榜」。这是加 `RankingKind` 成员时**唯一**会红的老测试。

`WarReportArmy` 列按规格 §5.3.2。约束**显式命名**，与迁移文件逐字一致 —— `Base` 没有配
`naming_convention`，`unique=True` 会落成 Postgres 自动名 `warreport_armies_canonical_key_key`，
和迁移里手写的名字对不上，以后 `alembic revision --autogenerate` 会反复生成「删约束/建约束」：

```python
__table_args__ = (
    UniqueConstraint("canonical_key", name="uq_warreport_armies_canonical_key"),
    Index("ix_warreport_armies_position", "position"),
)
```

两点容易漏：

- `Float` 需要加进 `models.py` 顶部的 `from sqlalchemy import (...)` 列表；
- 类追加到文件**末尾**（`BaseLayout` 之后），不要插在 `Ranking` 与 `CollectorRun`
  之间 —— 那个位置属于「排行榜」小节，`CollectorRun` 是「采集」小节的表头。
  `migrations/env.py` 只 import 模型模块，位置不影响 autogenerate，只影响可读性。

迁移文件：

```python
revision = "c3f9a1b7d204"
down_revision = "b2e8f4c17a93"
```

`upgrade()` 建表（列名/类型与模型逐字对齐）+ `ix_warreport_armies_position` 索引 +
`uq_warreport_armies_canonical_key` 唯一约束；`downgrade()` 先删索引与表
（唯一约束随表一起 DROP，不用单独删）。

**手写迁移，不要 `--autogenerate`。** 理由见 `backend/AGENTS.md`：autogenerate 依赖
`migrations/env.py` 把模型 import 进来，漏了会静默产出空迁移；手写一遍只需 20 行，
还能顺手把约束名写对。写完后用
`python -m pytest tests/db/test_warreport_models.py -q` 证明表真的建出来了。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/db/test_warreport_models.py tests/db/test_rankings_refresh.py -q`
Expected: PASS（conftest 会自动 `alembic upgrade head`）

- [ ] **Step 5: 提交**

```bash
git add backend/app/collector/rankings_service.py backend/app/db/models.py \
  backend/migrations/versions/0012_warreport_armies.py \
  backend/tests/db/test_warreport_models.py backend/tests/db/test_rankings_refresh.py
git commit -m "feat: 新增 War Report 阵容表与赛季榜类型"
```

---

### Task 5: 采集 job、调度与 run_job 客户端选择

**Files:**
- Create: `backend/app/collector/jobs/warreport.py`
- Modify: `backend/app/collector/service.py`（`JOBS` + 客户端选择）
- Modify: `backend/app/collector/scheduler.py`（`SCHEDULE_SPEC`）
- Modify: `backend/tests/collector/test_jobs.py:638`
- Modify: `backend/tests/collector/test_scheduler.py:120-126`
- Test: `backend/tests/collector/test_warreport_job.py`

**Interfaces:**
- Produces:
  - `async def collect_warreport(client, session, now: dt.datetime | None = None) -> dict`
  - `JOBS["warreport"]`
- Consumes: Task 1–4 的 client / mappers / snapshots / `WarReportArmy` / `RankingKind`

- [ ] **Step 1: 写失败测试**

```python
import datetime as dt
from datetime import UTC

from sqlalchemy import func, select

from app.collector.jobs.warreport import collect_warreport
from app.collector.rankings_service import RankingKind
from app.collector.service import run_job
from app.db.models import CollectorRun, Ranking, WarReportArmy
from app.warreport.client import WarReportError, WarReportSnapshotNotFound

NOW = dt.datetime.now(UTC)
TODAY = NOW.date().isoformat()


class FakeWarReport:
    def __init__(self, snapshots, fail=()):
        self.snapshots = set(snapshots)
        self.fail = set(fail)

    async def get_json(self, path, params=None):
        if path.endswith("/players/countries"):
            season = params["season"]
            if season not in self.snapshots:
                raise WarReportSnapshotNotFound("snapshot not found")
            return []
        if path in self.fail:
            raise WarReportError("boom", status_code=503)
        if path.endswith("/rankings/players"):
            return [{"tag": "#p1", "name": "P1", "rank": 1, "expLevel": 300,
                     "trophies": 6000, "attackWins": 3, "defenseWins": 2,
                     "clan": {"tag": "#c1", "name": "C1", "clanLevel": 18}}]
        if path.endswith("/rankings/clans"):
            return [{"tag": "#c1", "name": "C1", "rank": 1, "clanLevel": 18,
                     "members": 45, "clanPoints": 5000}]
        if path == "/armies":
            return [{"name": "Thrower", "canonicalKey": "k1",
                     "armyShareCode": "sc", "armyLink": "https://link",
                     "playerCount": 54, "useCount": 332, "percentage": 27.27,
                     "averageStars": 2.73, "averageDestruction": 97.25}]
        raise AssertionError(f"unexpected path {path}")


async def test_collect_writes_rankings_and_armies(session):
    result = await collect_warreport(FakeWarReport({TODAY}), session, now=NOW)
    assert result["items_ok"] == 3
    assert result["items_failed"] == 0

    players = (await session.execute(
        select(Ranking).where(Ranking.kind == str(RankingKind.wr_season_players))
    )).scalars().all()
    assert len(players) == 1
    assert players[0].season_id == TODAY
    assert players[0].location_id == 32000000
    assert players[0].clan_tag == "#C1"

    clans = (await session.execute(
        select(Ranking).where(Ranking.kind == str(RankingKind.wr_season_clans))
    )).scalars().all()
    assert clans[0].points == 5000

    armies = (await session.execute(select(WarReportArmy))).scalars().all()
    assert len(armies) == 1
    assert armies[0].position == 1


async def test_second_run_replaces_instead_of_duplicating(session):
    fake = FakeWarReport({TODAY})
    await collect_warreport(fake, session, now=NOW)
    await collect_warreport(fake, session, now=NOW)
    total = (await session.execute(
        select(func.count()).select_from(Ranking)
    )).scalar_one()
    assert total == 2
    assert (await session.execute(
        select(func.count()).select_from(WarReportArmy)
    )).scalar_one() == 1


async def test_partial_failure_keeps_other_scopes(session):
    status = await run_job(
        "warreport", session=session,
        client=FakeWarReport({TODAY}, fail={"/locations/global/rankings/clans"}),
    )
    assert status == "partial"
    assert (await session.execute(
        select(func.count()).select_from(Ranking)
    )).scalar_one() == 1
    run = (await session.execute(select(CollectorRun))).scalars().one()
    assert run.status == "partial"


async def test_discovery_failure_is_recorded_as_failed(session):
    class Broken(FakeWarReport):
        async def get_json(self, path, params=None):
            raise WarReportError("network down")

    status = await run_job("warreport", session=session, client=Broken(set()))
    assert status == "failed"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/collector/test_warreport_job.py -q`
Expected: FAIL

- [ ] **Step 3: 实现**

`collect_warreport` 流程（规格 §5.5）：

1. `known` = `SELECT DISTINCT season_id FROM rankings WHERE kind IN (...)
   AND season_id IS NOT NULL ORDER BY season_id DESC`（`IS NOT NULL` 别省：
   同一个 kind 若哪天混进别的 scope，NULL 会让 `known[0]` 变成一个没意义的锚点）。
2. `snapshots = await discover_snapshots(client, known, now.date())`。
3. 对每个 snapshot × `players`/`clans`：拉全量 → `[mapper(x) for x in raw]` 过滤
   `None` → `replace_rankings(session, kind, 32000000, None, snapshot, items, now=now)`
   → `commit()`。单 scope 异常 → `rollback()`、`failed += 1`、记明细。
4. `GET /armies` → 先拿事务级顾问锁 `pg_advisory_xact_lock(0x57524152)` →
   `DELETE FROM warreport_armies` → `session.add_all([WarReportArmy(**row) for ...])`
   → `commit()`。`row` 来自 `army_row(raw, position, now)`，`position` 从 **1** 开始
   按上游返回顺序编号（上游不提供序号，顺序即使用率降序）。
   **插入前按 `canonical_key` 去重**（保留先出现的那条，`position` 也随之紧凑）：
   上游若哪天返回两条同 key 的配兵，唯一约束会让整次 `commit()` 失败 —— 那时
   `DELETE` 已执行但事务回滚，数据是安全的，可阵容会永远停在旧版本且只有
   `collector_runs.error` 里能看到原因。去重把这种「上游脏数据」降级成无害事件。
5. 返回 `{"items_ok": ok, "items_failed": failed, "detail": [...]}`。

`service.py`：`JOBS` 加 `"warreport": collect_warreport`。两处类型标注必须一起放宽，
否则 `dict[str, Callable[[CocClient, ...]]]` 会拒收签名不同的 job（编辑器立刻报错）：

```python
JOBS: dict[str, Callable[[Any, AsyncSession], Awaitable[dict[str, Any]]]] = { ... }
```

`run_job` 的 `client` 形参放宽为 `CocClient | WarReportClient | None`。`service.py` 已有
`from __future__ import annotations`，所以注解是字符串、不会在导入期求值；为了让
类型检查器认得这个名字，补一个只对类型检查生效的导入：

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.warreport.client import WarReportClient
```

`owns_client` 分支里按 job 名选客户端，其余保持原样：

```python
if owns_client:
    effective = settings or get_settings()
    if job_name == "warreport":
        from app.warreport.client import client_from_settings
        client = client_from_settings(effective)
    else:
        client = CocClient(
            effective.coc_api_token,
            MemoryRateLimiter(rate=effective.coc_rate_limit),
            timeout=effective.coc_timeout,
            base_url=effective.coc_base_url,
        )
```

`aclose()` 仍只在 `owns_client` 时为真才调用 —— 两个客户端都有同名方法，无需分支。

`scheduler.py`：`SCHEDULE_SPEC` 加 `("23 4 * * *", "warreport", 86400)`。

同步修改两处既有断言：`test_jobs.py` 的 `set(service.JOBS)` 加 `"warreport"`；
`test_scheduler.py::test_schedule_spec_covers_the_four_jobs` 加 `"warreport"` 并
改名/注释为「五个 job」。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/collector/ -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/collector backend/tests/collector
git commit -m "feat: 新增 War Report 每日采集 job"
```

---

### Task 6: 赛季榜与阵容 API

**Files:**
- Create: `backend/app/api/routes/warreport.py`
- Modify: `backend/app/api/routes/rankings.py`（`_fresh_meta`/`_out` 改名并加 `ttl` 参数）
- Modify: `backend/app/main.py`（include router）
- Test: `backend/tests/api/test_rankings_warreport.py`（新建）
- Test: `backend/tests/api/test_armies.py`（新建）

**Interfaces:**
- Produces:
  - `GET /api/v1/rankings/warreport/seasons`
  - `GET /api/v1/rankings/warreport/seasons/{snapshot}/{kind}`
  - `GET /api/v1/armies`
- Consumes: `Ranking`、`WarReportArmy`、`RankingKind`、
  `app.api.routes.rankings.ranking_out`、`app.api.routes.rankings.fresh_meta`

- [ ] **Step 1: 写失败测试**

`test_rankings_warreport.py`：

```python
import datetime as dt
from datetime import UTC

import pytest

from app.collector.rankings_service import RankingKind
from app.db.models import Ranking

GLOBAL = 32000000
S1, S2 = "2026-10-05", "2026-09-07"


@pytest.fixture
async def boards(session):
    now = dt.datetime.now(UTC)
    rows = []
    for season in (S1, S2):
        for rank in range(1, 61):
            rows.append(Ranking(
                kind=str(RankingKind.wr_season_players), location_id=GLOBAL,
                season_id=season, rank=rank, tag=f"#P{rank}", name=f"P{rank}",
                trophies=6000 - rank, exp_level=300, fetched_at=now,
            ))
        rows.append(Ranking(
            kind=str(RankingKind.wr_season_clans), location_id=GLOBAL,
            season_id=season, rank=1, tag="#C1", name="C1",
            points=5000, members=45, clan_level=18, fetched_at=now,
        ))
    session.add_all(rows)
    await session.commit()


async def test_seasons_listed_newest_first_with_counts(client, boards):
    resp = await client.get("/api/v1/rankings/warreport/seasons")
    assert resp.status_code == 200
    body = resp.json()
    items = body["data"]["items"]
    assert [i["seasonId"] for i in items] == [S1, S2]
    assert items[0]["players"] == 60
    assert items[0]["clans"] == 1
    # fetchedAt 是 ISO 串（来自 max(fetched_at)），只断言存在且非空
    assert items[0]["fetchedAt"]
    assert body["meta"]["cache"] == "HIT"
    assert body["meta"]["ttl_seconds"] == 86400


async def test_season_board_paginates_and_clamps(client, boards):
    resp = await client.get(
        f"/api/v1/rankings/warreport/seasons/{S1}/players?page_size=100"
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["items"]) == 50
    assert data["total"] == 60
    assert data["kind"] == "players"


async def test_missing_snapshot_returns_empty_200(client, boards):
    resp = await client.get(
        "/api/v1/rankings/warreport/seasons/2026-01-01/players"
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["items"] == []


@pytest.mark.parametrize(
    "path",
    [
        # 月份 13 / 日期 99 合法形状但非法值
        "/api/v1/rankings/warreport/seasons/2026-13-99/players",
        # 少一位补零 —— 正则要求严格 \d{4}-\d{2}-\d{2}
        "/api/v1/rankings/warreport/seasons/2026-10-5/players",
        "/api/v1/rankings/warreport/seasons/not-a-date/players",
        f"/api/v1/rankings/warreport/seasons/{S1}/foo",
    ],
)
async def test_invalid_snapshot_or_kind_is_400(client, path):
    resp = await client.get(path)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAMS"


async def test_page_beyond_last_is_empty_200(client, boards):
    resp = await client.get(
        f"/api/v1/rankings/warreport/seasons/{S1}/players?page=999"
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["items"] == []
```

> 路径穿越**不要**用 `..%2F..%2Fetc` 去测：httpx 的 ASGI transport 会把 path 解码，
> Starlette 按 `/` 分段后根本匹配不到该路由，返回的是 404 而不是 400 —— 测出来的是
> 「路由不存在」而非「正则拦住了」。正则 `^\d{4}-\d{2}-\d{2}$` 本身已经排除了 `.` 与
> `/`，上面三个用例足够证明它在生效。

`test_armies.py`：

```python
import datetime as dt
from datetime import UTC

from app.db.models import WarReportArmy


async def test_armies_ordered_by_position(client, session):
    now = dt.datetime.now(UTC)
    session.add_all([
        WarReportArmy(position=2, name="B", canonical_key="b",
                      army_share_code="s2", army_link="https://b",
                      player_count=1, use_count=2, percentage=20.0,
                      average_stars=2.0, average_destruction=80.0,
                      fetched_at=now),
        WarReportArmy(position=1, name="A", canonical_key="a",
                      army_share_code="s1", army_link="https://a",
                      player_count=2, use_count=3, percentage=30.0,
                      average_stars=3.0, average_destruction=90.0,
                      fetched_at=now),
    ])
    await session.commit()

    resp = await client.get("/api/v1/armies")
    assert resp.status_code == 200
    body = resp.json()
    assert [i["name"] for i in body["data"]["items"]] == ["A", "B"]
    assert body["data"]["items"][0]["armyLink"] == "https://a"
    assert body["meta"]["cache"] == "HIT"


async def test_empty_armies_is_miss(client):
    resp = await client.get("/api/v1/armies")
    assert resp.status_code == 200
    assert resp.json()["data"]["items"] == []
    assert resp.json()["meta"]["cache"] == "MISS"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/api/test_rankings_warreport.py tests/api/test_armies.py -q`
Expected: FAIL（404）

- [ ] **Step 3: 实现**

- `rankings.py` 里两个小助手改成**可复用**（只是改名 + 加参数，行为不变）：
  - `_fresh_meta(fetched_at)` → `fresh_meta(fetched_at, ttl: int = 21600)`，把硬编码的
    `ttl_seconds=21600` 换成 `ttl`。默认值保持现有所有调用的行为，`rankings.py` 内部
    6 处调用不用改。
  - `_out(row)` → `ranking_out(row)`（名字变公开，逻辑一字不改），`rankings.py` 内 2 处
    调用跟着改名。
  - 为什么改名而不是直接 import `_out`：跨模块 import 私有名会让「这是内部实现」的
    信号失效；`warreport.py` 复用这两个函数是**设计意图**（赛季榜与实时榜必须同形状），
    所以名字就该是公开的。
- `warreport.py`（自己写 `_session()` 小助手，与 `content.py` / `upgrade.py` 一致，
  不跨模块借）：
  - `router = APIRouter(prefix="/api/v1")`
  - `_SNAPSHOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")`
  - **正则只拦形状，必须再用 `dt.date.fromisoformat(snapshot)` 验日历合法性**（R2）：
    `2026-13-99` 完全符合 `^\d{4}-\d{2}-\d{2}$`，只查正则会把它放进 SQL。
    两步都不过 → 400。
  - `_KIND_MAP = {"players": RankingKind.wr_season_players, "clans": RankingKind.wr_season_clans}`
  - 非法 snapshot / kind → `HTTPException(400, detail={"code": "INVALID_PARAMS", "message": ...})`
    （`main.py` 的 `StarletteHTTPException` handler 会把它转成
    `{"error": {"code": ..., "message": ...}}`，与现有 `/leagues/{kind}` 一致）
  - 赛季列表：`GROUP BY season_id, kind` 取 count 与 `max(fetched_at)`，Python 侧按
    `season_id` 合并成 `{"players": n, "clans": m}`，倒序取前 3；`meta=fresh_meta(最新, ttl=86400)`。
  - 赛季榜：与 `rankings._ranking_page` 同样的分页（`clamp_page_size`）+ `ranking_out`；
    `data.kind` 返回**路径值**（`players` / `clans`），不是 `wr_season_players`。
  - 阵容：`ORDER BY position`，字段转 camelCase，`meta=fresh_meta(最新, ttl=86400)`。
- `main.py`：`from app.api.routes import warreport` 并
  `app.include_router(warreport.router)`（放在 `rankings.router` 之后即可，路径段数不同，
  与 `/rankings/{kind}` 不会互相截胡）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/api/test_rankings_warreport.py tests/api/test_armies.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/routes/warreport.py backend/app/api/routes/rankings.py \
  backend/app/main.py backend/tests/api/test_rankings_warreport.py \
  backend/tests/api/test_armies.py
git commit -m "feat: 新增 War Report 赛季榜与阵容接口"
```

---

### Task 7: 前端 API 封装与署名组件

**Files:**
- Modify: `frontend/src/api/endpoints.ts`
- Create: `frontend/src/components/SourceNote.vue`
- Test: `frontend/src/api/endpoints.spec.ts`（新建）
- Test: `frontend/src/components/SourceNote.spec.ts`（新建）

**Interfaces:**
- Produces:
  - `type RankingEntity = RankingKind`（**别名，不重复定义联合类型**）
  - `interface WarReportSeason { seasonId: string; players: number; clans: number; fetchedAt: string | null }`
  - `interface ArmyRow { ... }`
  - `getWarReportSeasons()`、`getWarReportSeasonRankings(snapshot, entity, page, pageSize)`、`getArmies()`
  - `<SourceNote />`
- Consumes: `request`

`RankingKind` 已经存在且取值域就是 `'clans' | 'players'`（`endpoints.ts:83`）。
**不要**再写一份同样的联合类型 —— 两份定义迟早会漂移（后端加一类榜时只改一处）。
用别名把「榜单种类」与「榜单针对的实体」这两个说法对齐：

```ts
/** 榜单针对的实体。与 `RankingKind` 取值域相同，只是借一个更贴切的语义名。 */
export type RankingEntity = RankingKind
```

- [ ] **Step 1: 写失败测试**

`endpoints.spec.ts`：

```typescript
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./request', () => ({ request: vi.fn() }))

import { request } from './request'
import {
  getArmies,
  getWarReportSeasonRankings,
  getWarReportSeasons,
} from './endpoints'

describe('War Report 接口封装', () => {
  beforeEach(() => vi.mocked(request).mockReset())

  it('赛季列表走 warreport/seasons', async () => {
    vi.mocked(request).mockResolvedValue({ data: { items: [] }, meta: {} } as never)
    await getWarReportSeasons()
    expect(request).toHaveBeenCalledWith('/api/v1/rankings/warreport/seasons')
  })

  it('赛季榜用蛇形 page_size，并把 kind 放进路径', async () => {
    vi.mocked(request).mockResolvedValue({ data: {}, meta: {} } as never)
    await getWarReportSeasonRankings('2026-10-05', 'players', 2, 50)
    expect(request).toHaveBeenCalledWith(
      '/api/v1/rankings/warreport/seasons/2026-10-05/players',
      { params: { page: 2, page_size: 50 } },
    )
  })

  it('阵容接口固定 /api/v1/armies', async () => {
    vi.mocked(request).mockResolvedValue({ data: { items: [] }, meta: {} } as never)
    await getArmies()
    expect(request).toHaveBeenCalledWith('/api/v1/armies')
  })
})
```

`SourceNote.spec.ts`：

```typescript
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import SourceNote from './SourceNote.vue'

describe('SourceNote', () => {
  it('署名可见且链接到 warreport.app', () => {
    const w = mount(SourceNote)
    expect(w.text()).toContain('War Report')
    expect(w.text()).toContain('非 Supercell 官方')
    expect(w.find('a').attributes('href')).toBe('https://warreport.app')
    expect(w.find('a').attributes('rel')).toContain('noopener')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npm run test -- src/api/endpoints.spec.ts src/components/SourceNote.spec.ts`
Expected: FAIL

- [ ] **Step 3: 实现**

`endpoints.ts` 增加 `RankingEntity` 别名、`WarReportSeason` / `ArmyRow` 类型与三个函数：

```ts
export function getWarReportSeasons(): Promise<Envelope<{ items: WarReportSeason[] }>> {
  return request<{ items: WarReportSeason[] }>('/api/v1/rankings/warreport/seasons')
}

export function getWarReportSeasonRankings(
  snapshot: string,
  entity: RankingEntity,
  page = 1,
  pageSize = 20,
): Promise<Envelope<RankingsPage>> {
  return request<RankingsPage>(
    `/api/v1/rankings/warreport/seasons/${snapshot}/${entity}`,
    { params: { page, page_size: pageSize } },
  )
}

export function getArmies(): Promise<Envelope<{ items: ArmyRow[] }>> {
  return request<{ items: ArmyRow[] }>('/api/v1/armies')
}
```

`getRankings` 的形参类型从 `RankingKind` 改为 `RankingEntity`（同一个别名，纯语义收敛，
值域不变，不影响调用方）。

`SourceNote.vue`：链接写 `href="https://warreport.app"`、`target="_blank"`、
`rel="noopener noreferrer"`，锚文本为 `War Report`；整句文案
「数据来源：War Report · 非 Supercell 官方，未获 Supercell 背书」。
样式只用主题变量（`--text-faint` / `--accent-gold`），别写死颜色。

- [ ] **Step 4: 跑测试确认通过**

Run: `npm run test -- src/api/endpoints.spec.ts src/components/SourceNote.spec.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/api/endpoints.ts frontend/src/api/endpoints.spec.ts \
  frontend/src/components/SourceNote.vue frontend/src/components/SourceNote.spec.ts
git commit -m "feat: 前端接入 War Report 接口与署名组件"
```

---

### Task 8: 排行榜双页签与赛季切换

**Files:**
- Modify: `frontend/src/components/RankingTable.vue`
- Modify: `frontend/src/components/RankingTable.spec.ts`
- Modify: `frontend/src/pages/Rankings.vue`
- Modify: `frontend/src/pages/Rankings.spec.ts`

**Interfaces:**
- Produces: `RankingTable` 的 prop 改为 `entity: RankingEntity`
- Consumes: Task 7 的 `getWarReportSeasons` / `getWarReportSeasonRankings` / `SourceNote`

- [ ] **Step 1: 写失败测试**

`RankingTable.spec.ts`：`mountTable` 的第二个形参从 `kind` 改名 `entity`，挂载时传
`props: { rows, entity }`（**不是** `kind`）；其余用例的调用点跟着改。新增：

```typescript
it('prop 名是 entity，值域只有 clans / players', () => {
  const w = mountTable([row({ tag: '#AAA' })], 'players')
  expect(w.props('entity')).toBe('players')
})
```

`Rankings.spec.ts`：先把顶层 mock 扩成三个函数（**现有 `getRankings` 的断言一条都不要改**），
并在 `beforeEach` 里给两个新 mock 兜底返回值 —— 不兜底的话「切到赛季榜」的用例会因为
`getWarReportSeasons()` 返回 `undefined` 而掉进 error 分支：

```typescript
vi.mock('../api/endpoints', () => ({
  GLOBAL_LOCATION_ID: 32000000,
  getRankings: vi.fn(),
  getWarReportSeasons: vi.fn(),
  getWarReportSeasonRankings: vi.fn(),
}))

const seasonsPage = {
  data: {
    items: [
      { seasonId: '2026-10-05', players: 200, clans: 200, fetchedAt: null },
      { seasonId: '2026-09-07', players: 200, clans: 200, fetchedAt: null },
    ],
  },
  meta: rankingsPage.meta,
}

// beforeEach 里追加：
vi.mocked(getWarReportSeasons).mockReset()
vi.mocked(getWarReportSeasonRankings).mockReset()
vi.mocked(getWarReportSeasons).mockResolvedValue(seasonsPage as never)
vi.mocked(getWarReportSeasonRankings).mockResolvedValue(rankingsPage as never)
```

新增用例：

```typescript
async function switchToSeason(w: Awaited<ReturnType<typeof mountRankings>>) {
  const tabs = w.findComponent({ name: 'ElTabs' })
  await tabs.vm.$emit('update:modelValue', 'season')
  await flushPromises()
}

it('默认停在实时榜，不请求赛季数据', async () => {
  await mountRankings()
  expect(getRankings).toHaveBeenCalledWith('clans', 32000000, 1, 20)
  expect(getWarReportSeasons).not.toHaveBeenCalled()
})

it('切到赛季榜：默认选最新赛季并拉取', async () => {
  const w = await mountRankings()
  await switchToSeason(w)
  expect(getWarReportSeasons).toHaveBeenCalled()
  expect(getWarReportSeasonRankings).toHaveBeenCalledWith(
    '2026-10-05', 'clans', 1, 20,
  )
  expect(w.text()).toContain('数据来源：War Report')
})

it('切赛季回到第 1 页并重新拉取', async () => {
  const w = await mountRankings()
  await switchToSeason(w)
  vi.mocked(getWarReportSeasonRankings).mockClear()
  // 必须按 class 定位：el-pagination 的 layout 含 sizes，自己也会渲染一个
  // el-select，`findComponent({ name: 'ElSelect' })` 拿到的可能是分页器那个。
  const select = w.findComponent('.season-select')
  await select.vm.$emit('update:modelValue', '2026-09-07')
  await flushPromises()
  expect(getWarReportSeasonRankings).toHaveBeenCalledWith(
    '2026-09-07', 'clans', 1, 20,
  )
})

it('赛季列表为空时显示空态，不卡在 loading', async () => {
  vi.mocked(getWarReportSeasons).mockResolvedValue({
    data: { items: [] }, meta: rankingsPage.meta,
  } as never)
  const w = await mountRankings()
  await switchToSeason(w)
  expect(w.text()).toContain('暂无赛季数据')
  // LoadingBlock 用的是 skeleton、没有「加载中」字样，所以断言 DOM 而不是文案
  expect(w.find('.loading-block').exists()).toBe(false)
})
```

> 现有用例「只提供部落与玩家两个榜种」断言 `.el-radio-button__inner` 恰好是
> `['部落', '玩家']`。它之所以还能过，全靠赛季面板是 **lazy** 的 —— 见 Step 3。
> 若把 lazy 去掉，两个面板同时挂载会变成 4 个 radio，这条用例立刻红。

- [ ] **Step 2: 跑测试确认失败**

Run: `npm run test -- src/components/RankingTable.spec.ts src/pages/Rankings.spec.ts`
Expected: FAIL

- [ ] **Step 3: 实现**

- `RankingTable.vue`：`defineProps<{ rows: RankingRow[]; entity: RankingEntity }>()`；
  `METRIC_COLUMNS` 的键类型改为 `RankingEntity`；`PLAYER_KINDS` 改名 `PLAYER_ENTITIES`
  （类型 `RankingEntity[]`）；`metricColumns` / `detailRoute` 全部读 `props.entity`。
- `Rankings.vue`：
  - 顶层 `el-tabs v-model="view"`，两个 `el-tab-pane`：`realtime`（默认）与 `season`。
    **赛季那个必须加 `lazy`**，否则现有「只有两个榜种」的用例会红，而且首次进入页面
    会白打一次赛季接口。
  - 两套**互相独立**的状态：实时用 `realtimeEntity/realtimeRows/realtimeTotal/
    realtimePage/realtimePageSize/...`；赛季用 `seasonEntity/seasonRows/seasonTotal/
    seasonPage/seasonPageSize/seasonSnapshot/seasons/...`。共用一个 `entity` ref 会让
    在赛季面板切部落/玩家时把实时榜也重拉一遍（多余的请求 + 两个 loading 互相覆盖）。
  - 实时面板：现有逻辑原样搬过去，只把提示改成
    「全服 · 线上经 RoyaleAPI 代理，约每 6 小时刷新」。
  - 赛季面板：
    - `watch(view)`：第一次切到 `season` 时调 `loadSeasons()`（用 `seasonsLoaded`
      布尔量守住，切回再切走不重复请求列表）。
    - `loadSeasons()` 成功后把 `seasonSnapshot` 设为 `items[0]?.seasonId`；列表为空
      就只显示「暂无赛季数据」，**不要**发榜请求、也不要停在 loading。
    - `watch([seasonSnapshot, seasonEntity])` → `seasonPage = 1` 并重拉；
      `seasonSnapshot` 为 `null` 时直接返回。
    - 模板：`el-select` + 部落/玩家 `el-radio-group` + `RankingTable :entity` +
      `el-pagination`（page-sizes 同实时），面板底部固定渲染 `<SourceNote />`
      （即使空列表也要有署名）。赛季 `el-select` **必须带 class `season-select`** ——
      测试靠它定位（分页器自己也有一个 el-select），见 Step 1 的注释。
  - 分页越界：赛季面板用 `@current-change` / `@size-change` 与实时面板同一套写法。

- [ ] **Step 4: 跑测试确认通过**

Run: `npm run test -- src/components/RankingTable.spec.ts src/pages/Rankings.spec.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/RankingTable.vue frontend/src/components/RankingTable.spec.ts \
  frontend/src/pages/Rankings.vue frontend/src/pages/Rankings.spec.ts
git commit -m "feat: 排行榜拆成实时榜与赛季榜"
```

---

### Task 9: 阵容页、阵型占位、导航与页脚

**Files:**
- Create: `frontend/src/pages/Armies.vue`
- Create: `frontend/src/pages/Armies.spec.ts`
- Create: `frontend/src/pages/Bases.vue`
- Create: `frontend/src/pages/Bases.spec.ts`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/router/index.spec.ts`
- Modify: `frontend/src/layouts/MainLayout.vue`
- Modify: `frontend/src/layouts/MainLayout.spec.ts`

**Interfaces:**
- Produces: 路由 `armies`（`/armies`）、`bases`（`/bases`）；导航四项；全站页脚
- Consumes: Task 7 的 `getArmies` / `ArmyRow` / `SourceNote`

- [ ] **Step 1: 写失败测试**

`Armies.spec.ts`：

```typescript
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/endpoints', () => ({ getArmies: vi.fn() }))

import { getArmies } from '../api/endpoints'
import { installElementPlus } from '../plugins/element'
import Armies from './Armies.vue'

const page = {
  data: { items: [{
    position: 1, name: 'Thrower', canonicalKey: 'k1', armyShareCode: 'sc',
    armyLink: 'https://link.clashofclans.com/?action=CopyArmy&army=sc',
    playerCount: 54, useCount: 332, percentage: 27.27,
    averageStars: 2.73, averageDestruction: 97.25,
  }] },
  meta: { cache: 'HIT', fetchedAt: null, ageSeconds: null, ttlSeconds: 86400 },
}

describe('Armies', () => {
  beforeEach(() => {
    vi.mocked(getArmies).mockReset()
    vi.mocked(getArmies).mockResolvedValue(page as never)
  })

  it('渲染配兵名、使用率与平均星', async () => {
    const w = mount(Armies, { global: { plugins: [{ install: installElementPlus }] } })
    await flushPromises()
    expect(w.text()).toContain('Thrower')
    expect(w.text()).toContain('27.3%')
    expect(w.text()).toContain('2.73')
    expect(w.text()).toContain('数据来源：War Report')
  })

  it('空数据显示空态', async () => {
    vi.mocked(getArmies).mockResolvedValue({
      data: { items: [] }, meta: page.meta,
    } as never)
    const w = mount(Armies, { global: { plugins: [{ install: installElementPlus }] } })
    await flushPromises()
    expect(w.text()).toContain('暂无数据')
  })

  it('没有 clipboard 时退化打开链接，不抛未捕获异常', async () => {
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const w = mount(Armies, { global: { plugins: [{ install: installElementPlus }] } })
    await flushPromises()
    await w.find('.army-card__copy').trigger('click')
    await flushPromises()
    expect(open).toHaveBeenCalledWith(page.data.items[0].armyLink, '_blank')
  })
})
```

`Bases.spec.ts`：断言渲染「阵型功能开发中，敬请期待」。

`router/index.spec.ts` 增加：

```typescript
await router.push('/armies')
expect(document.title).toBe(`阵容 · ${APP_TITLE}`)
await router.push('/bases')
expect(document.title).toBe(`阵型 · ${APP_TITLE}`)
```

`MainLayout.spec.ts`：**改**现有用例（它现在叫「导航只含查询与排行榜」，名字与断言都要
跟着需求走，不能只是新增一条把它晾在那儿）。测试自带的 router 也要补两条路由，
否则 `router-link` 会对着不存在的路径刷 warning：

```typescript
// 测试用 router 里补：
{ path: '/armies', name: 'armies', component: { template: '<div/>' } },
{ path: '/bases', name: 'bases', component: { template: '<div/>' } },
```

```typescript
it('导航是查询 / 排行榜 / 阵容 / 阵型四项', () => {
  const w = mount(MainLayout, { global: { plugins: [router] } })
  expect(w.findAll('.app-nav__link').map((a) => a.text())).toEqual([
    '查询', '排行榜', '阵容', '阵型',
  ])
  // 仍未上线的功能不该出现
  expect(w.text()).not.toContain('投稿')
  expect(w.text()).not.toContain('公告')
})

it('页脚声明数据来源', () => {
  const w = mount(MainLayout, { global: { plugins: [router] } })
  expect(w.find('footer.app-footer').text()).toContain(
    '数据来源：Supercell 官方 API、War Report',
  )
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npm run test -- src/pages/Armies.spec.ts src/pages/Bases.spec.ts src/router/index.spec.ts src/layouts/MainLayout.spec.ts`
Expected: FAIL

- [ ] **Step 3: 实现**

- `Armies.vue`：卡片网格（窄屏单列）；每张卡展示配兵名、使用率、使用次数、玩家数、
  平均星级、平均摧毁率，以及按钮 `.army-card__copy`。格式化：`percentage` 用
  `toFixed(1)` 加 `%`、`averageStars` 与 `averageDestruction` 用 `toFixed(2)`。
  `onMounted` 拉 `getArmies()`；失败用 `ErrorCard`（与 `Rankings.vue` 同一个
  `toApiError` 写法）；空列表显示「暂无数据」；页尾固定渲染 `<SourceNote />`。
  顶部说明：「数据来自 War Report，统计对象为前 200 名传奇联赛玩家」。
  `ElMessage` 从 `element-plus` 显式 import（项目没有全局注入 `$message`）。

```ts
async function copyLink(link: string) {
  try {
    if (!navigator.clipboard) throw new Error('no clipboard')
    await navigator.clipboard.writeText(link)
    ElMessage.success('已复制阵型链接')
  } catch {
    // 非 HTTPS 或旧浏览器没有 clipboard：退化成打开链接，用户可自行复制
    window.open(link, '_blank')
  }
}
```

- `Bases.vue`：标题「阵型」+ 一张占位卡片，文案「阵型功能开发中，敬请期待」。
  不建表、不建接口、不发任何请求。
- `router/index.ts`：加两条 lazy 路由（`armies` → `Armies.vue`，`bases` →
  `Bases.vue`），`meta.title` 分别为 `阵容` / `阵型`；位置放在 `/rankings` 之后、
  兜底路由之前。
- `MainLayout.vue`：`NAV_ITEMS` 追加 `{ path: '/armies', label: '阵容' }` 与
  `{ path: '/bases', label: '阵型' }`；`<main>` 之后加
  `<footer class="app-footer">`，文案
  「本站为非官方粉丝站点 · 数据来源：Supercell 官方 API、War Report」。
  页脚样式写在同一 `<style scoped>` 里，只用主题变量
  （`--border-default` / `--text-faint` / `--page-max` / `--page-gutter`），
  **别写死颜色**；`--page-max` 与 `--page-gutter` 保证与 header 左右对齐。

- [ ] **Step 4: 跑测试确认通过**

Run: `npm run test -- src/pages/Armies.spec.ts src/pages/Bases.spec.ts src/router/index.spec.ts src/layouts/MainLayout.spec.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/Armies.vue frontend/src/pages/Armies.spec.ts \
  frontend/src/pages/Bases.vue frontend/src/pages/Bases.spec.ts \
  frontend/src/router frontend/src/layouts
git commit -m "feat: 新增阵容页与阵型占位页"
```

---

### Task 10: 部署资产、配置样例与文档署名

**Files:**
- Modify: `.env.example`
- Modify: `backend/.env.example`
- Modify: `docker-compose.yml`
- Modify: `backend/docker-compose.yml`
- Modify: `docs/deployment.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Test: `backend/tests/test_root_deployment_assets.py`
- Test: `backend/tests/test_deployment_config.py`

**Interfaces:**
- Consumes: 无（纯配置/文档）

- [ ] **Step 1: 写失败测试**

`test_root_deployment_assets.py` 增加：

```python
def test_api_passes_warreport_env():
    env = _compose()["services"]["api"]["environment"]
    assert "WARREPORT_BASE_URL" in env
    assert "WARREPORT_TIMEOUT" in env


def test_deployment_doc_credits_war_report():
    doc = (REPO_ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")
    assert "War Report" in doc
    assert "署名" in doc
    assert "https://warreport.app" in doc
```

`test_deployment_config.py` 增加：

```python
def test_env_example_has_warreport_base_url():
    assert "WARREPORT_BASE_URL" in _read(".env.example")


def test_backend_compose_passes_warreport_env():
    env = _compose()["services"]["api"]["environment"]
    assert "WARREPORT_BASE_URL" in env
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_root_deployment_assets.py tests/test_deployment_config.py -q`
Expected: FAIL（缺变量 / 缺文档）

- [ ] **Step 3: 实现**

- 根 `.env.example` 与 `backend/.env.example`：

```dotenv
# War Report（赛季榜 / 阵容）。无需 Key；上游要求署名，见 docs/deployment.md §12。
WARREPORT_BASE_URL=https://api.warreport.app
WARREPORT_TIMEOUT=15
```

- 根 `docker-compose.yml` 的 `api.environment` 与 `backend/docker-compose.yml` 的
  `api.environment` 各加：

```yaml
WARREPORT_BASE_URL: ${WARREPORT_BASE_URL:-https://api.warreport.app}
WARREPORT_TIMEOUT: ${WARREPORT_TIMEOUT:-15}
```

- `docs/deployment.md`：新增 `## 12. War Report 数据源与署名`，原 `## 12. 已知问题`
  改为 `## 13. 已知问题`。新节必须包含：
  - 用途、端点、每日 `04:23 UTC` 一次、无 Key/白名单；
  - 署名原文与本站落点（赛季榜、阵容页、全站页脚）；
  - `https://warreport.app` 链接；
  - 非 Supercell 官方 / Fan Content Policy；
  - 快照探测与 404 `snapshot not found` 是正常结果；
  - 验证命令 `python -m app.cli collect warreport`；
  - 上游不可用时的表现（旧数据 + `collector_runs`，不 500）。
- `README.md` 功能清单加「赛季榜 / 阵容 / 阵型（占位）」与数据来源一行。
- `AGENTS.md` 在「未完成的欠账」或合适位置加一条：
  「赛季榜与阵容数据来自 War Report，**署名是使用条件**；改相关页面前先读
  `docs/deployment.md` §12。」

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_root_deployment_assets.py tests/test_deployment_config.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add .env.example backend/.env.example docker-compose.yml \
  backend/docker-compose.yml docs/deployment.md README.md AGENTS.md \
  backend/tests/test_root_deployment_assets.py backend/tests/test_deployment_config.py
git commit -m "docs: 补 War Report 部署说明与署名"
```

---

### Task 11: 全量验证与手工冒烟

**Files:**
- 不改代码（只验证；发现问题回到对应任务修）

- [ ] **Step 1: 后端全量测试**

Run: `python -m pytest -q`（`backend/` 下）
Expected: 全绿，无 failed / error。

- [ ] **Step 2: 前端测试与构建**

Run: `npm run test`（`frontend/` 下）
Expected: 全绿。
Run: `npm run build`
Expected: `vue-tsc` 无类型错误，`vite build` 成功。

- [ ] **Step 3: 手工冒烟（需要 `backend/.env` 与本地 PG）**

```powershell
# 1) 起 PG（若未起）
C:\pgportable\pgsql\bin\pg_isready.exe -h 127.0.0.1 -p 5433 -U postgres
# 2) 迁移 + 真实上游采集
cd backend
python -m app.cli collect warreport
# 3) 查接口
python -m uvicorn app.main:app --port 8000
curl http://127.0.0.1:8000/api/v1/rankings/warreport/seasons
curl "http://127.0.0.1:8000/api/v1/rankings/warreport/seasons/2026-10-05/players?page_size=5"
curl http://127.0.0.1:8000/api/v1/armies
```

Expected：
- `collect warreport` 输出 `success`（首次会逐日回溯 + 按 28 天补探，约 25 次小请求）；
- 赛季列表 3 条（`2026-10-05` / `2026-09-07` / `2026-08-10`，具体日期以当日上游为准）；
- 赛季榜 `total` 为 200；
- 阵容条数**不要写死 55** —— 该接口返回的是「当前快照里出现过的配兵」，实测
  2026-10-23 只有 13 条（之前调研时的 55 条是另一天的快照）。断言「非空且
  `position` 从 1 连续」即可。

> 首次采集要逐日回溯 19 次 `players/countries`（每次 3.8 KB），命中后再按 28 天
> 间隔补探两档（最多 6 次）。这**不是**故障，是「上游没有赛季列表接口」的必然代价；
> 第二次运行起只探 3 个候选日期。

- [ ] **Step 4: 浏览器冒烟**

起 `npm run dev`，逐项确认：
- 排行榜默认实时榜；切赛季榜能看到 3 个日期并切换；
- 阵容页显示配兵、复制按钮可用；
- 阵型页显示占位；
- 页脚与两处署名可见。

- [ ] **Step 5: 最终提交（如有验证中产生的小修）**

```bash
git status --short
git add <修改的文件>
git commit -m "test: 完成 War Report 接入的全量验证"
```
