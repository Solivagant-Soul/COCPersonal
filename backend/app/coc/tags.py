"""tag 归一化：大小写与 URL 编码。

COC 的 tag 大小写不敏感，但有两处会让小写 tag 出问题：

1. **入库重复** —— 直接用用户输入做键，`#2pp` 与 `#2PP` 会变成两行。
2. **URL 被截断** —— `#` 是 URL 片段起始符，不编码的话 httpx 会把它及之后的内容丢掉，
   请求实际发出去的是 `/clans/`，官方返回 4xx，而表面上像是"部落不存在"。

这两件事只在这里做一次。Task 7（映射器）与 Task 11（榜单刷新）必须复用本模块，
不得自行 `strip().upper()` —— 已经有三处这么干过，每处都漏了编码。
"""

from __future__ import annotations

from urllib.parse import quote


def normalize_tag(tag: str) -> str:
    """归一化为 `#大写` 形式。

    只剥离开头的 `#`：开头的 `#` 是用户输入习惯带的，tag 内部的 `#` 官方不认可
    但也不该由我们静默删掉（删了会请求到一个不存在的 tag，错误信息会指向别处）。
    """
    return "#" + tag.strip().lstrip("#").upper()


def quote_tag(tag: str) -> str:
    """把归一化后的 tag 编码成 URL 路径片段。

    ``safe=""`` 是必须的：默认会让 `/` 免编码，而 `#` 在默认的 safe 集合之外本就会
    被编码，但显式写空更稳妥，也防止未来有人改 safe 集合时悄悄破坏tag。
    """
    return quote(normalize_tag(tag), safe="")
