"""B 站置顶笔记里的阵型代码 → 官方复制链接。

视频简介只说「链接在评论区置顶笔记」，评论正文里是 ``TH18:WB:xxxx`` 这样的
分享码（部分带 ``#1`` / ``1号`` 编号，部分编号与代码分两行）。本模块只做
纯文本解析，**不发网络请求**，方便单测；抓评论在 ``fetch_pinned`` 里。
"""

from __future__ import annotations

import re
from urllib.parse import quote

#: 官方复制阵型的 URL 模板。
BASE = "https://link.clashofclans.com/?action=OpenLayout&id="

# 编号 + 分隔符 + 代码。`\s*` 故意包含换行：置顶笔记常见「#19：」空一行再给代码。
# 分隔符允许「号 + 冒号」同时出现（`1号：`），也允许只有其中一个。
_CODE_RE = re.compile(
    r"(?:#|第)?\s*(\d{1,2})\s*(?:号\s*[:：]?|[:：])\s*"
    r"(TH\d{1,2}:[A-Z]{2}:[A-Za-z0-9_-]+)"
)


def normalize_layout_link(code: str) -> str:
    """分享码 → 官方链接；已经是 http(s) URL 就原样返回。"""
    text = code.strip()
    if text.startswith(("http://", "https://")):
        return text
    return BASE + quote(text, safe="")


def parse_layout_codes(text: str) -> dict[int, str]:
    """从评论正文里抽 ``编号 → 复制链接``。

    **只收带编号的代码**：没有编号就无法和视频里的 ``#N`` 角标对应，
    强行按出现顺序编号会把「网友自填的国服码」错配到别的阵型上。
    后出现的同编号覆盖前面的（UP 常在后面补更正）。
    """
    links: dict[int, str] = {}
    for match in _CODE_RE.finditer(text):
        number = int(match.group(1))
        links[number] = normalize_layout_link(match.group(2))
    return links


def extract_pinned_texts(payload: dict) -> list[str]:
    """从评论接口响应里取置顶评论正文；置顶为空时退回普通评论。"""
    data = payload.get("data") or {}
    replies = data.get("top_replies") or data.get("replies") or []
    texts = []
    for reply in replies:
        content = reply.get("content") or {}
        message = content.get("message")
        if isinstance(message, str):
            texts.append(message)
    return texts
