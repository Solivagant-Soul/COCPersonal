"""把一条阵型上传到站点。

只依赖 ``requests``；鉴权是 HTTP Basic（复用后台的 ADMIN_USERNAME / ADMIN_PASSWORD）。
"""

from __future__ import annotations

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
) -> dict:
    """POST 一条阵型，返回响应里的 ``data``。

    后端对重复内容返回 200 + ``duplicated=true``，这里不视为失败。
    """
    url = api_base.rstrip("/") + "/api/v1/admin/bases"
    image_path = Path(image)
    files = {
        "image": (image_path.name, image_path.read_bytes(), "image/jpeg"),
    }
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

    if resp.status_code >= 400:
        message = resp.text
        try:
            message = resp.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            pass
        raise UploadError(resp.status_code, str(message))

    body = resp.json()
    return body.get("data", body)
