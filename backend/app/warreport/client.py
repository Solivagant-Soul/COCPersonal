"""War Report（https://api.warreport.app）的 HTTP 客户端。

职责边界与 ``app/coc/client.py`` 一致：只管 HTTP 层 —— 发请求、把响应翻译成
:class:`WarReportError` 系列异常。**不**做数据映射（那是 mappers 的事），
**不**缓存，也**不**打时间戳（mapper 的 ``now`` 一律由调用方注入）。

War Report 是第三方只读 API，不需要 key，也没有官方的令牌桶；因此这里不做
限速与重试 —— 重试策略属于调用方（采集器）的决策。
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings

#: 上游表达"该赛季/地区的快照还没生成"的方式：404 + 这条文案。
#: 它是**业务态**（明天再来就有），与真正的上游故障要分开。
SNAPSHOT_NOT_FOUND_MARKER = "snapshot not found"


class WarReportError(RuntimeError):
    """War Report 调用失败。

    ``status_code`` 为 ``None`` 表示没拿到 HTTP 响应（网络错误、非 JSON 响应体）。
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class WarReportSnapshotNotFound(WarReportError):
    """该赛季/地区的快照不存在（上游 404 + ``snapshot not found``）。"""


class WarReportClient:
    """War Report API 客户端。

    ``transport`` 是测试注入点：测试用 ``httpx.MockTransport``，
    生产用默认的异步传输。
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # 去掉尾斜杠：httpx 把 base_url 与 path 原样相接，留着会拼出 ``//armies``
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url, timeout=timeout, transport=transport
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_json(self, path: str, params: dict[str, str] | None = None) -> Any:
        """GET ``path`` 并把响应体解析成 JSON。

        判定顺序（见计划 Task 1）：网络错误 → 快照不存在 → 其它 4xx/5xx →
        JSON 解析失败。除快照不存在外，所有失败都是 :class:`WarReportError`。
        """
        try:
            response = await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise WarReportError(f"GET {path} 请求失败: {exc}") from exc

        status = response.status_code
        if status == 404 and SNAPSHOT_NOT_FOUND_MARKER in response.text.lower():
            raise WarReportSnapshotNotFound(
                f"GET {path} 快照不存在: {_snippet(response)}", status_code=status
            )
        if status >= 400:
            raise WarReportError(
                f"GET {path} 失败: {status} {_snippet(response)}", status_code=status
            )

        try:
            return response.json()
        except ValueError as exc:
            raise WarReportError(f"GET {path} 返回了非 JSON 响应体: {exc}") from exc


def client_from_settings(settings: Settings) -> WarReportClient:
    """按配置构造客户端。调用方负责 ``aclose()``。"""
    return WarReportClient(
        settings.warreport_base_url, timeout=settings.warreport_timeout
    )


def _snippet(response: httpx.Response, limit: int = 200) -> str:
    """错误信息里带上响应体片段（截断），便于排查上游改了什么。"""
    return response.text[:limit]
