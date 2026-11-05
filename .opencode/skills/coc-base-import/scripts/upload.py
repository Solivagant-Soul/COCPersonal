"""把一条阵型上传到站点。

只依赖 ``requests``；鉴权是 HTTP Basic（复用后台的 ADMIN_USERNAME / ADMIN_PASSWORD）。
"""

from __future__ import annotations

import time
from pathlib import Path

import requests


class UploadError(RuntimeError):
    """上传失败：``status`` 为 HTTP 状态码（网络错误为 0）。"""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def upload_one(
    image: Path,
    payload: dict[str, object],
    api_base: str,
    user: str,
    password: str,
    timeout: int = 30,
    max_attempts: int = 4,
) -> dict:
    """POST 一条阵型，返回响应里的 ``data``。

    后端对重复内容返回 200 + ``duplicated=true``，这里不视为失败。

    **429 要重试**：站点的对外限流是 60 次/分钟/IP，30 条连发 + 列表请求很容易
    顶到边界；真实跑第二轮时就出现过「重复 22、失败 8」，8 条全是 429。
    优先用 ``Retry-After``，没有就指数退避。
    """
    url = api_base.rstrip("/") + "/api/v1/admin/bases"
    image_path = Path(image)
    body = image_path.read_bytes()

    for attempt in range(1, max_attempts + 1):
        files = {"image": (image_path.name, body, "image/jpeg")}
        try:
            resp = requests.post(
                url,
                data=payload,
                files=files,
                auth=(user, password),
                timeout=timeout,
            )
        except requests.RequestException as exc:  # 连接失败 / 超时
            raise UploadError(0, f"网络错误：{exc}") from exc

        if resp.status_code == 429 and attempt < max_attempts:
            delay = resp.headers.get("Retry-After")
            time.sleep(float(delay) if delay and delay.isdigit() else 2 ** attempt)
            continue
        if resp.status_code >= 400:
            message = resp.text
            try:
                message = resp.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                pass
            raise UploadError(resp.status_code, str(message))

        payload_json = resp.json()
        return payload_json.get("data", payload_json)

    raise UploadError(429, "被限流且重试次数用尽")  # pragma: no cover - 循环内已返回/抛出
