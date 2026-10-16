"""COC 官方 API 错误层次。

锁住两个关键设计：
1. 业务态（部落不存在/未在战/战报私密）与故障态（限流/上游异常/超时）分层，
   使调用方能据 type 决定重试还是转 HTTP 码。
2. ``CocAccessDenied`` 与 ``CocProtocolError`` 必须是 ``CocError`` 的**直接**子类
   —— 归到 ``CocFaultError`` 会让客户端的重试循环自动重试，而 IP 白名单不匹配时
   重试毫无意义，只会白白烧掉令牌桶额度。
"""

from app.coc.errors import (
    ClanNotFound,
    CocAccessDenied,
    CocBusinessError,
    CocError,
    CocFaultError,
    CocProtocolError,
    CocThrottled,
    CocTimeout,
    CocUpstreamError,
    NotInWar,
    PlayerNotFound,
    WarLogPrivate,
)


async def test_business_errors_derive_from_business_error():
    for cls in (ClanNotFound, PlayerNotFound, NotInWar, WarLogPrivate):
        assert issubclass(cls, CocBusinessError), f"{cls.__name__} 应为业务错误"


async def test_fault_errors_derive_from_fault_error():
    for cls in (CocThrottled, CocUpstreamError, CocTimeout):
        assert issubclass(cls, CocFaultError), f"{cls.__name__} 应为故障错误"


async def test_access_denied_is_not_a_fault_error():
    """accessDenied 不得被归入故障态，否则会被自动重试。"""
    assert not issubclass(CocAccessDenied, CocFaultError)


async def test_protocol_error_is_not_a_fault_error():
    assert not issubclass(CocProtocolError, CocFaultError)


async def test_access_denied_and_protocol_error_are_direct_children():
    """必须是直接子类，中间不能夹任何层。"""
    assert CocAccessDenied.__bases__ == (CocError,)
    assert CocProtocolError.__bases__ == (CocError,)


async def test_business_and_fault_bases_are_not_peers():
    """业务态与故障态不得互相继承。"""
    assert not issubclass(CocBusinessError, CocFaultError)
    assert not issubclass(CocFaultError, CocBusinessError)


async def test_reasons_are_class_attributes_matching_official_api():
    assert ClanNotFound.reason == "notFound"
    assert PlayerNotFound.reason == "notFound"
    assert NotInWar.reason == "notInWar"
    assert WarLogPrivate.reason == "privateWarLog"
    assert CocThrottled.reason == "requestThrottled"
    assert CocUpstreamError.reason == "unknownException"
    assert CocTimeout.reason == "requestAborted"
    assert CocAccessDenied.reason == "accessDenied"


async def test_exception_carries_a_human_message():
    err = ClanNotFound("部落不存在")
    assert str(err) == "部落不存在"


async def test_constructor_can_carry_precise_upstream_reason():
    """规格要求 accessDenied.invalidIp 单独告警，故需能携带上游精确 reason。"""
    err = CocAccessDenied("IP 不在白名单", "accessDenied.invalidIp")
    assert err.reason == "accessDenied.invalidIp"


async def test_default_reason_is_used_when_no_override():
    assert CocAccessDenied(" denied").reason == "accessDenied"
