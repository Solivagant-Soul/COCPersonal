"""B 站置顶笔记里的阵型代码 → 官方复制链接。

视频简介只说「链接在评论区置顶笔记」。置顶可能是：

- 评论正文里的 ``TH18:WB:xxxx`` 分享码（部分带 ``#1`` / ``1号`` 编号）；
- 一条 ``bilibili.com/opus/<id>`` 动态笔记；
- 一条 ``read/cv<id>`` 专栏 —— **本视频就是这种**：评论只挂 ``note_cvid``，
  正文在 ``x/article/view`` 里，格式是「编号一行、完整链接一行」。

解析器同时认「编号 + 分享码」和「编号 + 完整链接」两种写法；抓取函数带 cookie
时可复用登录态，没有 cookie 时按匿名请求（公开内容通常也能读到）。
"""

from __future__ import annotations

import html
import re
import time
from pathlib import Path
from urllib.parse import quote

#: 官方复制阵型的 URL 模板。
BASE = "https://link.clashofclans.com/?action=OpenLayout&id="

# 编号 + 分隔符 + 值。`\s*` 故意包含换行：置顶笔记常见「19：」空一行再给内容。
# 分隔符允许「号 + 冒号」同时出现（`1号：`），也允许只有其中一个。
# 值有两种：分享码（`TH18:WB:...`）或完整链接（**只认官方域名**——
# 置顶评论被折叠成 80 字符预览时会出现 `https://li...` 这种截断尾巴，
# 放宽成任意 URL 就会把它当成第 1 号阵型写进库）。
_VALUE_RE = r"(TH\d{1,2}:[A-Z]{2}:[A-Za-z0-9_-]+)|(https?://link\.clashofclans\.com/[^\s<>\"']+)"
_CODE_RE = re.compile(
    r"(?:#|第)?\s*(\d{1,2})\s*(?:号\s*[:：]?|[:：])\s*(?:" + _VALUE_RE + r")"
)

#: 置顶评论里指向笔记（opus）的链接。
_OPUS_RE = re.compile(r"https?://(?:www\.)?bilibili\.com/opus/(\d+)")

#: 从笔记 JSON 里收集正文时认的键名。
_TEXT_KEYS = frozenset({"text", "orig_text", "title"})

#: 链接末尾可能粘上的中文/英文标点，不属于 URL。
_TRAILING = "，。、；）),.;"


def normalize_layout_link(code: str) -> str:
    """分享码 → 官方链接；已经是 http(s) URL 就原样返回。"""
    text = code.strip()
    if text.startswith(("http://", "https://")):
        return text
    return BASE + quote(text, safe="")


def parse_layout_codes(text: str) -> dict[int, str]:
    """从评论/笔记正文里抽 ``编号 → 复制链接``。

    **只收带编号的条目**：没有编号就无法和视频里的 ``#N`` 角标对应，
    强行按出现顺序编号会把「网友自填的国服码」错配到别的阵型上。
    后出现的同编号覆盖前面的（UP 常在后面补更正）。
    """
    links: dict[int, str] = {}
    for match in _CODE_RE.finditer(html.unescape(text)):
        number = int(match.group(1))
        value = match.group(2) or match.group(3)
        links[number] = normalize_layout_link(value.rstrip(_TRAILING))
    return links


def html_to_text(raw: str) -> str:
    """专栏正文是 HTML：段落/换行标签转成换行，其余标签去掉，实体反转义。"""
    text = re.sub(r"</p\s*>|<br\s*/?>", "\n", raw)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


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
    """按 Netscape cookie 文件建一个带 UA / Referer 的 requests 会话。

    **cookie 文件缺失不报错**：公开视频的置顶评论与专栏匿名也能读
    （2026-11 实测），只是遇到风控才有必要登录。文件损坏时照常抛错。
    """
    import http.cookiejar

    import requests

    session = requests.Session()
    session.headers.update({"User-Agent": _UA, "Referer": "https://www.bilibili.com/"})

    cookies_path = Path(cookies_path)
    if cookies_path.is_file():
        jar = http.cookiejar.MozillaCookieJar(str(cookies_path))
        jar.load(ignore_discard=True, ignore_expires=True)
        session.cookies.update(jar)
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


def fetch_pinned_payload(bvid: str, cookies_path: Path) -> dict:
    """取视频的置顶评论**原始响应**（置顶正文可能是被截断的预览）。

    优先走 ``x/v2/reply/wbi/main``（带签名）；它被风控时退回老的
    ``x/v2/reply`` —— 后者匿名可用，且会把置顶的 ``note_cvid`` 一并带出来。
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

    try:
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
        if reply.get("code") == 0:
            return reply
    except (RuntimeError, ValueError):
        pass

    legacy = session.get(
        "https://api.bilibili.com/x/v2/reply",
        params={"oid": aid, "type": 1, "sort": 2, "ps": 20},
        timeout=15,
    ).json()
    if legacy.get("code") != 0:
        raise RuntimeError(f"取评论失败：{legacy.get('code')} {legacy.get('message')}")
    return legacy


def fetch_pinned(bvid: str, cookies_path: Path) -> list[str]:
    """取视频的置顶评论正文。"""
    return extract_pinned_texts(fetch_pinned_payload(bvid, cookies_path))


def extract_pinned_cvids(payload: dict) -> list[str]:
    """置顶评论挂着的「笔记」cvid（B 站会把长正文折叠成一条笔记卡片）。"""
    cvids: list[str] = []
    for reply in (payload.get("data") or {}).get("top_replies") or []:
        cvid = str(reply.get("note_cvid_str") or reply.get("note_cvid") or "").strip()
        if cvid and cvid != "0" and cvid not in cvids:
            cvids.append(cvid)
    return cvids


#: B 站风控/限流的临时错误码：睡两秒重试基本就过。
_TRANSIENT_CODES = frozenset({-352, -412, -509})


def fetch_article(cvid: str, cookies_path: Path) -> dict[str, object]:
    """抓一条 ``read/cv<id>`` 专栏的正文（置顶笔记最常见的形式）。

    返回 ``{"texts": [纯文本], "raw": <原始响应>}``。

    ``-352`` / ``-412`` / ``-509`` 都是 IP/频率级的风控码。**退避重试**：连续
    撞上时 2s / 4s / 8s / 16s 递增，通常一两轮后就能拿到正文（2026-11 实测）。
    """
    session = _session_from_cookies(cookies_path)
    payload: dict = {}
    for delay in (2, 4, 8, 16, None):
        payload = session.get(
            "https://api.bilibili.com/x/article/view",
            params={"id": cvid},
            timeout=15,
        ).json()
        if payload.get("code") not in _TRANSIENT_CODES:
            break
        if delay is None:
            break
        time.sleep(delay)

    if payload.get("code") != 0:
        raise RuntimeError(
            f"取专栏 cv{cvid} 失败：{payload.get('code')} {payload.get('message')}"
        )
    content = (payload.get("data") or {}).get("content") or ""
    return {"texts": [html_to_text(str(content))], "raw": payload}


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
