"""API 层共享：响应体、分页常量、错误码映射。

``MAX_PAGE_SIZE`` / ``DEFAULT_PAGE_SIZE`` / ``clamp_page_size`` 是**全项目唯一的**
分页截断点。Task 13 / 16 / 17 的分页路由一律复用，不得各自定义上限 ——
四处手写 ``min(page_size, 50)`` 的后果是某一处漏改、且没人知道哪处是对的。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50


def clamp_page_size(page_size: int) -> int:
    """把分页大小夹到 [1, MAX_PAGE_SIZE]。

    **截断而非拒绝**：调用方给 ``page_size=500`` 时返回截断后的 50 + HTTP 200，
    而不是 422。理由（Review Focus 第 4 条）：官方只接受 1–50，透传会得到
    ``badRequest``；让调用方因一个可自动修正的参数吃 422 不合理。
    """
    return min(max(page_size, 1), MAX_PAGE_SIZE)


class MetaOut(BaseModel):
    """统一 meta。``cache`` 值必须是大写 HIT / MISS / STALE（规格 §6.1）。"""

    cache: str
    fetched_at: datetime | None = None
    age_seconds: int | None = None
    ttl_seconds: int


class DataOut(BaseModel):
    data: object
    meta: MetaOut


class ErrorBody(BaseModel):
    code: str
    message: str
    # 官方 reason（如 accessDenied.invalidIp），便于 §7.4 的告警规则消费
    upstream_reason: str | None = None


class ErrorOut(BaseModel):
    error: ErrorBody


class PageParams(BaseModel):
    """分页参数的公共解析。"""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit

    @property
    def limit(self) -> int:
        return clamp_page_size(self.page_size)
