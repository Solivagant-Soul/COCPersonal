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
        assert request.url.params["season"] == "2026-10-04"
        return httpx.Response(404, json={"error": "snapshot not found"})

    with pytest.raises(WarReportSnapshotNotFound):
        await _client(handler).get_json(
            "/locations/global/rankings/players", {"season": "2026-10-04"}
        )


async def test_plain_404_is_not_mistaken_for_missing_snapshot():
    """只有带上游那句文案的 404 才是"快照还没生成"，其余 404 仍是普通错误。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "unknown route"})

    with pytest.raises(WarReportError) as exc:
        await _client(handler).get_json("/nope")
    assert not isinstance(exc.value, WarReportSnapshotNotFound)
    assert exc.value.status_code == 404


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

    with pytest.raises(WarReportError) as exc:
        await _client(handler).get_json("/armies")
    assert exc.value.status_code is None


async def test_non_json_body_maps_to_war_report_error():
    """上游偶发返回 HTML 错误页；放过去调用方会拿到一个长得像数据的字符串。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>oops</html>")

    with pytest.raises(WarReportError) as exc:
        await _client(handler).get_json("/armies")
    assert exc.value.status_code is None


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
    # 路径必须锚在本文件上，不能写相对的 ``Path("app/warreport")``：那要求
    # 调用者的 CWD 正好是 ``backend/``。从仓库根跑（`python -m pytest backend/...`）
    # 或换个工作目录时，rglob 扫不到任何文件，offenders 恒为空 —— 边界测试
    # 会**永远通过**，无论代码里加了什么依赖。下面的非空断言就是这道保险。
    package = Path(__file__).resolve().parents[2] / "app" / "warreport"
    files = sorted(package.rglob("*.py"))
    assert files, f"没扫到任何文件，路径边界测试已失效：{package}"

    offenders = []
    for path in files:
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
