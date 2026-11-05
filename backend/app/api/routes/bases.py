"""阵型（基地布局）路由。

对外只暴露**已发布**的阵型；草稿与未审内容一律不出现在列表里。
图片由 `media` 卷承载，库里只存 `/media/...` 相对 URL，具体托管见
`docs/deployment.md` §15。

上传走 HTTP Basic（复用后台的 `ADMIN_USERNAME` / `ADMIN_PASSWORD`），
**任一环境变量为空就一律 401** —— 否则空凭据会被 ``"" == ""`` 放行，
等于把上传接口完全公开。
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import os
import secrets
import uuid
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from app.api.schemas import DEFAULT_PAGE_SIZE, DataOut, MetaOut, clamp_page_size
from app.db.models import BaseLayout
from app.db.session import new_session

router = APIRouter(prefix="/api/v1")

#: 单张图片上限。超过立刻 413，不落盘。
MAX_IMAGE_BYTES = 5 * 1024 * 1024

#: 阵型链接 / 来源 URL 的长度上限。
MAX_URL_LENGTH = 2048


def base_layout_out(row: BaseLayout) -> dict[str, object]:
    """单条阵型的对外形状（camelCase）。"""
    return {
        "id": row.id,
        "title": row.title,
        "thLevel": row.th_level,
        "layoutLink": row.layout_link,
        "imagePath": row.image_path,
        "sourceUrl": row.source_url,
        "sourceSite": row.source_site,
        "createdAt": row.created_at,
    }


def _meta(cache: str = "HIT") -> MetaOut:
    """内容型数据没有上游回源，`ttl_seconds=0`。"""
    return MetaOut(cache=cache, fetched_at=None, age_seconds=None, ttl_seconds=0)


def _media_root() -> Path:
    """取媒体根目录。

    **每次调用都读 settings**，测试用 monkeypatch 换掉本函数即可把文件导到
    ``tmp_path``；不要在模块导入期固化。
    """
    from app.config import get_settings

    return Path(get_settings().media_root)


def detect_image_ext(head: bytes) -> str | None:
    """按 magic bytes 判定图片类型；不是 JPEG/PNG/WebP 一律 ``None``。

    **不看文件名也不看 Content-Type**：两者都是客户端说了算，拿来判类型
    等于让任何人往 `/media/` 里塞任意内容。
    """
    if head[:3] == b"\xff\xd8\xff":
        return "jpg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def check_basic_auth(header: str | None, username: str, password: str) -> bool:
    """校验 ``Authorization: Basic`` 头。任一配置凭据为空 → 直接失败。

    **按字节比较**：``secrets.compare_digest`` 只接受 ASCII 字符串，中文账号或
    口令会抛 ``TypeError``（500）；先编码成 UTF-8 再比，既支持非 ASCII，也保持
    定长比较。
    """
    if not username or not password:
        return False
    if not header:
        return False
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "basic" or not token:
        return False
    try:
        raw = base64.b64decode(token, validate=True)
    except ValueError:
        return False
    supplied_user, sep, supplied_pass = raw.partition(b":")
    if not sep:
        return False
    return secrets.compare_digest(supplied_user, username.encode("utf-8")) and (
        secrets.compare_digest(supplied_pass, password.encode("utf-8"))
    )


def compute_layout_hash(
    title: str,
    th_level: int | None,
    layout_link: str | None,
    source_url: str | None,
    image: bytes,
) -> str:
    """内容指纹，用于上传幂等（同一内容重传不再写文件、不再插行）。"""
    image_digest = hashlib.sha256(image).hexdigest() if image else ""
    payload = "|".join(
        [
            "v1",
            title,
            "" if th_level is None else str(th_level),
            layout_link or "",
            source_url or "",
            image_digest,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def save_image(
    data: bytes, ext: str, media_root: Path, now: dt.datetime
) -> str:
    """写 ``{root}/bases/YYYY/MM/{uuid}.{ext}``，返回 ``/media/...`` 相对 URL。"""
    rel_dir = Path("bases") / f"{now:%Y}" / f"{now:%m}"
    target = media_root / rel_dir
    target.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    (target / name).write_bytes(data)
    return f"/media/{rel_dir.as_posix()}/{name}"


def mount_media(app: FastAPI, media_root: Path | None = None) -> None:
    """把媒体目录挂到 ``/media``，供本地开发与自托管使用。

    **目录不存在就什么都不做**（也不创建）：生产上 ``/data/media`` 由卷提供；
    本地首次上传前先手工建 ``backend/.media``，否则挂载会跳过，图片要重启后
    才可访问。
    """
    root = media_root if media_root is not None else _media_root()
    if root.is_dir():
        app.mount("/media", StaticFiles(directory=root), name="media")


def _unauthorized(message: str) -> JSONResponse:
    """401 必须自带 ``WWW-Authenticate``。

    不能用 ``HTTPException``：统一错误处理器重建响应，会把这里的头丢掉。
    """
    return JSONResponse(
        status_code=401,
        content={
            "error": {
                "code": "UNAUTHORIZED",
                "message": message,
                "upstream_reason": None,
            }
        },
        headers={"WWW-Authenticate": 'Basic realm="coc-admin"'},
    )


def _invalid(message: str) -> HTTPException:
    return HTTPException(
        status_code=400, detail={"code": "INVALID_PARAMS", "message": message}
    )


def _clean_url(value: object) -> str | None:
    """校验可选 URL 字段：空 → ``None``；非 http(s) 或过长 → 400。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > MAX_URL_LENGTH:
        raise _invalid(f"URL 过长（上限 {MAX_URL_LENGTH} 字符）")
    if not text.startswith(("http://", "https://")):
        raise _invalid("URL 必须以 http:// 或 https:// 开头")
    return text


@router.get("/bases", response_model=None)
async def list_bases(
    th_level: int | None = Query(default=None, ge=1, le=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1),
):
    limit = clamp_page_size(page_size)
    stmt = select(BaseLayout).where(BaseLayout.is_published.is_(True))
    if th_level is not None:
        stmt = stmt.where(BaseLayout.th_level == th_level)

    session = new_session()
    try:
        total = (
            await session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        rows = (
            (
                await session.execute(
                    stmt.order_by(
                        BaseLayout.created_at.desc(), BaseLayout.id.desc()
                    )
                    .offset((page - 1) * limit)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    finally:
        await session.close()

    return DataOut(
        data={"items": [base_layout_out(row) for row in rows], "total": total},
        meta=_meta(),
    )


@router.post("/admin/bases", response_model=None)
async def create_base(request: Request):
    """管理员上传一条阵型，上传即发布。"""
    ok = check_basic_auth(
        request.headers.get("authorization"),
        os.environ.get("ADMIN_USERNAME", ""),
        os.environ.get("ADMIN_PASSWORD", ""),
    )
    if not ok:
        return _unauthorized("需要管理员凭据")

    form = await request.form()

    title = str(form.get("title") or "").strip()
    if not title:
        raise _invalid("标题不能为空")
    if len(title) > 100:
        raise _invalid("标题最长 100 个字符")

    th_level: int | None = None
    raw_th = form.get("th_level")
    if raw_th is not None and str(raw_th).strip():
        try:
            th_level = int(str(raw_th).strip())
        except ValueError:
            raise _invalid("大本等级必须是整数")
        if not 1 <= th_level <= 100:
            raise _invalid("大本等级必须在 1-100 之间")

    layout_link = _clean_url(form.get("layout_link"))
    source_url = _clean_url(form.get("source_url"))

    source_site = str(form.get("source_site") or "bilibili").strip() or "bilibili"
    if len(source_site) > 50:
        raise _invalid("来源站点名最长 50 个字符")

    image_bytes = b""
    image_ext: str | None = None
    upload = form.get("image")
    if upload is not None and hasattr(upload, "read"):
        image_bytes = await upload.read(MAX_IMAGE_BYTES + 1)
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "PAYLOAD_TOO_LARGE",
                    "message": f"图片不能超过 {MAX_IMAGE_BYTES // (1024 * 1024)} MiB",
                },
            )
        image_ext = detect_image_ext(image_bytes[:12])
        if image_ext is None:
            raise _invalid("图片格式不受支持（仅 JPEG / PNG / WebP）")

    if layout_link is None and not image_bytes:
        raise _invalid("阵型链接与图片至少上传一个")

    content_hash = compute_layout_hash(
        title, th_level, layout_link, source_url, image_bytes
    )
    now = dt.datetime.now(dt.UTC)

    session = new_session()
    try:
        existing = (
            (
                await session.execute(
                    select(BaseLayout).where(BaseLayout.content_hash == content_hash)
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            data = base_layout_out(existing) | {"duplicated": True}
            return JSONResponse(
                status_code=200,
                content=jsonable_encoder(DataOut(data=data, meta=_meta("HIT"))),
            )

        image_path = (
            save_image(image_bytes, image_ext, _media_root(), now)
            if image_bytes
            else None
        )
        row = BaseLayout(
            title=title,
            th_level=th_level,
            layout_link=layout_link,
            image_path=image_path,
            source_url=source_url,
            source_site=source_site,
            content_hash=content_hash,
            copy_count=0,
            is_published=True,
            created_at=now,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return JSONResponse(
            status_code=201,
            content=jsonable_encoder(
                DataOut(
                    data=base_layout_out(row) | {"duplicated": False},
                    meta=_meta("MISS"),
                )
            ),
        )
    finally:
        await session.close()
