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

#: 置顶评论里指向笔记（opus）的链接。
_OPUS_RE = re.compile(r"https?://(?:www\.)?bilibili\.com/opus/(\d+)")

#: 从笔记 JSON 里收集正文时认的键名。
_TEXT_KEYS = frozenset({"text", "orig_text", "title"})


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


# --------------------------------------------------------------------------- #
# 抓置顶评论（wbi 签名 + 浏览器导出的 cookie）
# --------------------------------------------------------------------------- #

#: B 站 wbi 签名的固定打乱表（官方前端同款）。
_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61,
    26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36,
    20, 34, 44, 52,
]

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def extract_bvid(url: str) -> str:
    """从任意 B 站视频 URL 里取 BV 号。"""
    match = re.search(r"(BV[0-9A-Za-z]{10})", url)
    if not match:
        raise ValueError(f"URL 里没有 BV 号：{url!r}")
    return match.group(1)


def _mixin_key(img_key: str, sub_key: str) -> str:
    raw = img_key + sub_key
    return "".join(raw[index] for index in _MIXIN_KEY_ENC_TAB)[:32]


def _signed_params(params: dict[str, object], img_key: str, sub_key: str) -> dict[str, object]:
    import hashlib
    import time
    from urllib.parse import urlencode

    signed = dict(params)
    signed["wts"] = int(time.time())
    query = urlencode(sorted(signed.items()))
    signed["w_rid"] = hashlib.md5((query + _mixin_key(img_key, sub_key)).encode()).hexdigest()
    return signed


def extract_opus_ids(texts: list[str]) -> list[str]:
    """从评论文本里取 ``bilibili.com/opus/<id>`` 的笔记 id（去重、保序）。"""
    ids: list[str] = []
    for text in texts:
        for match in _OPUS_RE.finditer(text):
            if match.group(1) not in ids:
                ids.append(match.group(1))
    return ids


def _collect_texts(node: object) -> list[str]:
    """从任意 JSON 里收集所有正文片段。

    动态/笔记的正文既可能在 ``desc.text``，也可能拆在 ``rich_text_nodes[].text``，
    不同版本还换过字段名，所以按「键名是 text/title 就收」泛化处理；多收几条
    无关键名也不要紧 —— 后面只按编号正则匹配。
    """
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _TEXT_KEYS and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_collect_texts(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_collect_texts(value))
    return found


def _session_from_cookies(cookies_path: Path):
    """按 Netscape cookie 文件建一个带 UA / Referer 的 requests 会话。"""
    import http.cookiejar

    import requests

    cookies_path = Path(cookies_path)
    if not cookies_path.is_file():
        raise FileNotFoundError(
            f"找不到 B 站 cookie：{cookies_path}（浏览器导出 Netscape 格式后放到这里）"
        )

    jar = http.cookiejar.MozillaCookieJar(str(cookies_path))
    jar.load(ignore_discard=True, ignore_expires=True)
    session = requests.Session()
    session.cookies.update(jar)
    session.headers.update({"User-Agent": _UA, "Referer": "https://www.bilibili.com/"})
    return session


def _wbi_keys(session) -> tuple[str, str]:
    """取 wbi 签名用的 img_key / sub_key（每次请求现取，密钥会轮换）。"""
    nav = session.get("https://api.bilibili.com/x/web-interface/nav", timeout=15).json()
    wbi = nav.get("data", {}).get("wbi_img") or {}
    img_url = wbi.get("img_url", "")
    sub_url = wbi.get("sub_url", "")
    if not img_url or not sub_url:
        raise RuntimeError("取 wbi 签名密钥失败（cookie 可能已失效）")
    return (
        img_url.rsplit("/", 1)[-1].split(".")[0],
        sub_url.rsplit("/", 1)[-1].split(".")[0],
    )


def fetch_pinned(bvid: str, cookies_path: Path) -> list[str]:
    """取视频的置顶评论正文。

    **必须带登录 cookie**：匿名请求评论接口返回 403 / ``-352``。
    cookie 从浏览器导出为 Netscape 格式，放在 ``.secrets/bilibili-cookies.txt``。
    """
    session = _session_from_cookies(cookies_path)

    view = session.get(
        "https://api.bilibili.com/x/web-interface/view",
        params={"bvid": bvid},
        timeout=15,
    ).json()
    if view.get("code") != 0:
        raise RuntimeError(f"取视频信息失败：{view.get('code')} {view.get('message')}")
    aid = view["data"]["aid"]

    img_key, sub_key = _wbi_keys(session)
    params = _signed_params(
        {
            "oid": aid,
            "type": 1,
            "mode": 3,
            "pagination_str": '{"offset":""}',
            "plat": 1,
            "web_location": 1315875,
        },
        img_key,
        sub_key,
    )
    reply = session.get(
        "https://api.bilibili.com/x/v2/reply/wbi/main",
        params=params,
        timeout=15,
    ).json()
    if reply.get("code") != 0:
        raise RuntimeError(f"取评论失败：{reply.get('code')} {reply.get('message')}")
    return extract_pinned_texts(reply)


def fetch_opus(opus_id: str, cookies_path: Path) -> dict[str, object]:
    """抓一条 ``/opus/<id>`` 笔记的正文。

    返回 ``{"texts": [...], "raw": <原始响应>}``。``texts`` 为空说明正文是图片
    （UP 常把阵型代码贴在长图里），调用方应把 ``raw`` 落盘让人工看图。
    """
    session = _session_from_cookies(cookies_path)
    img_key, sub_key = _wbi_keys(session)
    params = _signed_params(
        {
            "id": opus_id,
            "timezone_offset": -480,
            "platform": "web",
            "features": "itemOpusStyle",
        },
        img_key,
        sub_key,
    )
    payload = session.get(
        "https://api.bilibili.com/x/polymer/web-dynamic/v1/detail",
        params=params,
        timeout=15,
    ).json()
    if payload.get("code") != 0:
        raise RuntimeError(
            f"取笔记 {opus_id} 失败：{payload.get('code')} {payload.get('message')}"
        )
    return {"texts": _collect_texts(payload.get("data")), "raw": payload}
