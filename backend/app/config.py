from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: 官方 API 地址。与 :data:`app.coc.client.BASE_URL` 保持一致。
OFFICIAL_COC_BASE_URL = "https://api.clashofclans.com/v1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    coc_api_token: str
    database_url: str
    app_role: str = "all"
    coc_rate_limit: int = 8
    coc_timeout: float = 15.0
    #: 对外每 IP 每分钟请求数（§6）。/healthz 与 /readyz 豁免。
    rate_limit_per_minute: int = 60
    #: 官方 API 地址。**留空 = 走官方**；
    #: 填 ``https://cocproxy.royaleapi.dev/v1`` 则走 RoyaleAPI 代理（见 AGENTS.md「上游接入」）。
    #: 代理只换域名，路径与鉴权不变。
    coc_base_url: str = ""
    #: War Report（第三方 COC 数据 API，无需 key）的地址与超时。
    warreport_base_url: str = "https://api.warreport.app"
    warreport_timeout: float = 15.0
    #: 后台会话 cookie 的签名密钥。**每个部署都必须换成随机值**：
    #: 签名密钥泄露等于任何人都能伪造管理员会话。
    admin_secret_key: str = "change-me-in-production"
    media_root: str = "/data/media"
    public_base_url: str
    log_level: str = "INFO"

    @field_validator("coc_base_url", mode="after")
    @classmethod
    def _default_base_url(cls, value: str) -> str:
        """空值回落到官方地址。

        `.env.example` 里 ``COC_BASE_URL=`` 是空值占位；不回落的话 pydantic 会把
        空字符串原样塞给 httpx，然后每个请求都以 ``InvalidURL`` 崩掉 ——
        而且只在生产配置下炸（测试全用打桩 transport，看不出来）。
        """
        stripped = value.strip()
        return stripped or OFFICIAL_COC_BASE_URL


@lru_cache
def get_settings() -> Settings:
    return Settings()
