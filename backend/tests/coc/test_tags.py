"""tag 归一化：大小写与 URL 编码。

COC 的 tag 大小写不敏感，但：
1. 用户从输入法/粘贴得到的可能是小写，直接入库会产生两行；
2. `#` 是 URL 片段起始符，不编码会被 httpx 截断，请求根本发不出去。

这两件事只在这里做一次，Task 7 / Task 11 也必须复用，不得各写一份。
"""

from app.coc.tags import normalize_tag, quote_tag


def test_normalize_tag_uppercases_and_adds_hash():
    assert normalize_tag("2pp") == "#2PP"


def test_normalize_tag_strips_surrounding_whitespace():
    assert normalize_tag("  #2pp  ") == "#2PP"


def test_normalize_tag_keeps_already_normalized_tag_unchanged():
    assert normalize_tag("#2PP") == "#2PP"


def test_normalize_tag_does_not_strip_interior_hash():
    """只有前导 # 是分隔符，tag 内部的 # 官方不认可但也不该被误删。"""
    assert normalize_tag("A#B") == "#A#B"


def test_quote_tag_encodes_hash_as_percent_23():
    assert quote_tag("2pp") == "%232PP"


def test_quote_tag_is_urlsafe_for_internal_hash():
    """内部 # 也必须编码，否则又被当片段符。"""
    assert quote_tag("A#B") == "%23A%23B"


def test_normalize_then_quote_is_idempotent_on_result():
    assert quote_tag(normalize_tag("2pp")) == quote_tag("2pp")
