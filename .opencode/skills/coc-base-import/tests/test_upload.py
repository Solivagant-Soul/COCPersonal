"""上传客户端的重试行为（不发真实请求）。"""

from pathlib import Path

import pytest
import upload


class FakeResponse:
    def __init__(self, status_code, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or str(payload)
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _image(tmp_path: Path) -> Path:
    path = tmp_path / "01.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    return path


def test_upload_retries_on_429_then_succeeds(tmp_path, monkeypatch):
    """站点的 60/min 限流会在大批量导入时打到，429 必须重试而不是记成失败。"""
    responses = [
        FakeResponse(429, {"error": {"message": "rate limited"}}, headers={"Retry-After": "1"}),
        FakeResponse(200, {"data": {"id": 7, "duplicated": False}}),
    ]

    def fake_post(*args, **kwargs):
        return responses.pop(0)

    slept = []
    monkeypatch.setattr(upload.requests, "post", fake_post)
    monkeypatch.setattr(upload.time, "sleep", lambda seconds: slept.append(seconds))

    data = upload.upload_one(_image(tmp_path), {"title": "x"}, "http://127.0.0.1:8000", "u", "p")

    assert data["id"] == 7
    assert slept == [1.0]


def test_upload_gives_up_after_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(
        upload.requests,
        "post",
        lambda *a, **k: FakeResponse(429, {"error": {"message": "rate limited"}}),
    )
    monkeypatch.setattr(upload.time, "sleep", lambda seconds: None)

    with pytest.raises(upload.UploadError) as excinfo:
        upload.upload_one(_image(tmp_path), {"title": "x"}, "http://h", "u", "p", max_attempts=3)

    assert excinfo.value.status == 429


def test_upload_reports_401_without_retry(tmp_path, monkeypatch):
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(1)
        return FakeResponse(401, {"error": {"message": "unauthorized"}})

    monkeypatch.setattr(upload.requests, "post", fake_post)
    monkeypatch.setattr(upload.time, "sleep", lambda seconds: None)

    with pytest.raises(upload.UploadError) as excinfo:
        upload.upload_one(_image(tmp_path), {"title": "x"}, "http://h", "u", "p")

    assert excinfo.value.status == 401
    assert len(calls) == 1
