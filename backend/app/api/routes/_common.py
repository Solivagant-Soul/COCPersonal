"""clans / players 两个路由模块共享的胶水。

**为什么要有这个模块**：``players.py`` 早先是 ``clans.py`` 的薄壳，把 ``_validate_tag``、
``_meta``、``_player_out`` 三个下���线函数从 ``clans`` 反向 import。后果是
``/players/{tag}`` 在两个 router 上各注册了一次 —— 运行时靠 include 顺序取胜（后 include
的覆盖前面的），测试全绿，OpenAPI 却一直报 Duplicate Operation ID。交叉 import 把这个
重复**藏住了**：谁都不会去数路由条数。

所以共享的东西放这里，且只放真正与资源无关的部分。资源专属的序列化器（如
``_player_out``）留在自己的模块里 —— 它只有一个主人，就不该"共享"。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from fastapi import HTTPException

from app.api.schemas import MetaOut
from app.coc.tags import normalize_tag
from app.db.session import get_session

# COC tag：# 可选前缀 + 3-10 位字母数字。不强制大写（#2pp 也受理，归一化后使用），
# 因为小程序用户从输入法/粘贴得到的标签大小写随机（Review Focus 第 1 条）。
_TAG_RE = re.compile(r"^#?[0-9A-Za-z]{3,10}$")


def validate_tag(tag: str) -> str:
    """校验并归一化一个 tag，不合法抛 400 INVALID_TAG。"""
    if not _TAG_RE.match(tag):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_TAG",
                "message": f"标签不合法: {tag!r}（应为 # 后 3-10 位字母数字）",
            },
        )
    return normalize_tag(tag)


async def open_session():
    """取一个 session。``get_session`` 是 async_generator，不能用 async with。"""
    return await anext(get_session())


def build_meta(status, fetched_at, ttl: int) -> MetaOut:
    """按 §6.1 组装 meta。

    ``cache`` 直接取 ``status.value`` —— 上游的 ``CacheStatus`` 已经是
    ``HIT``/``MISS``/``STALE`` 大写（§6.1 与 §3 数据流都是大写），小写会直接破坏前端契约。
    """
    return MetaOut(
        cache=status.value,
        fetched_at=fetched_at,
        age_seconds=(
            int((datetime.now(UTC) - fetched_at).total_seconds())
            if fetched_at is not None
            else None
        ),
        ttl_seconds=ttl,
    )


async def noop_persist(_data) -> None:
    """``read_through`` 的 persister 占位：只读资源不落库。"""
    return None