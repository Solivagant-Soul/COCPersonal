"""COC 官方 API 错误层次。

分成两族，调用方据此决定「转成 HTTP 码」还是「等一会儿再试」：

- 业务态（``CocBusinessError`` 及其子类）—— 接口正常应答但结果为空，
  如部落不存在、不在战中、战报私密。**绝不重试**，直接转 HTTP 码。
- 故障态（``CocFaultError`` 及其子类）—— 官方限流、上游异常、超时。
  可退避重试。

``CocAccessDenied`` 与 ``CocProtocolError`` 故意**不**归入故障态：前者代表
Token 过期或公网 IP 不在白名单，重试只会白白烧掉令牌桶额度；后者是我们自己
解析不出响应体，重试也修不好。二者在缓存层仍可降级为 STALE（见
``app/cache/readthrough.py``）—— 降级与重试是两个正交的决策。
"""

from __future__ import annotations


class CocError(Exception):
    """所有 COC 访问错误的基类。

    ``reason`` 是与官方 API ``reason`` 字段对齐的机器可读码，默认取类属性；
    构造时可以用第二个参数携带上游返回的精确值（例如
    ``accessDenied.invalidIp``，规格要求它单独告警）。
    """

    reason: str = "unknownException"

    def __init__(self, message: str = "", reason: str | None = None) -> None:
        super().__init__(message)
        if reason is not None:
            self.reason = reason


# --------------------------------------------------------------------------- #
# 业务态：接口正常，结果为空
# --------------------------------------------------------------------------- #


class CocBusinessError(CocError):
    """业务态基类。此类异常绝不重试。"""

    reason: str = "badRequest"


class ClanNotFound(CocBusinessError):
    reason: str = "notFound"


class PlayerNotFound(CocBusinessError):
    reason: str = "notFound"


class NotInWar(CocBusinessError):
    reason: str = "notInWar"


class WarLogPrivate(CocBusinessError):
    reason: str = "privateWarLog"


# --------------------------------------------------------------------------- #
# 故障态：可退避重试
# --------------------------------------------------------------------------- #


class CocFaultError(CocError):
    """故障态基类。此类异常可退避重试。"""

    reason: str = "unknownException"


class CocThrottled(CocFaultError):
    """被官方限流。"""

    reason: str = "requestThrottled"


class CocUpstreamError(CocFaultError):
    """官方返回 5xx 或未分类的异常。"""

    reason: str = "unknownException"


class CocTimeout(CocFaultError):
    """请求超时。"""

    reason: str = "requestAborted"


# --------------------------------------------------------------------------- #
# 既非业务态也非故障态：单独处理
# --------------------------------------------------------------------------- #


class CocAccessDenied(CocError):
    """官方返回 403。

    直连时最常见的是服务器 IP 不在白名单（``accessDenied.invalidIp``）或
    Token 过期；走 RoyaleAPI 代理（R26）时 = 代理 IP 被移出白名单、Token 过期，
    或代理本身限流。无论哪种，重试都无意义，但缓存层可据此降级为 STALE。
    """

    reason: str = "accessDenied"


class CocProtocolError(CocError):
    """响应体不是预期的 JSON，或字段结构不认识。"""

    reason: str = "unknownException"
