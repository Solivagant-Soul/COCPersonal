"""部署配置校验。

**配置错误是最难排查的一类 bug**：服务起来了、端口通了、但行为不对，
排查方向会完全跑偏。这里把"最容易踩的部署坑"变成测试：

- postgres 端口暴露到宿主机 = 数据库裸奔在公网上
- ``--workers > 1`` = 每个 worker 一个令牌桶 + 一个调度器，直接打爆 Supercell 限流
- nginx 不透传 X-Forwarded-For = 全网共用一个限流桶，一个人刷爆所有人被限
- ``.env.example`` 里有真实密钥 = 密钥进了 git 历史，再删也删不掉
"""

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parent.parent


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _compose() -> dict:
    return yaml.safe_load(_read("docker-compose.yml"))


# --------------------------------------------------------------------------- #
# 必须存在的文件
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path",
    [
        "Dockerfile",
        "docker-compose.yml",
        "deploy/nginx.conf",
        "deploy/certbot-renew.sh",
        "deploy/backup.sh",
        "docs/deployment.md",
        "docs/README.md",
        "docs/README-使用说明.md",
    ],
)
def test_deployment_file_exists(path):
    assert (ROOT / path).exists(), f"缺少部署文件: {path}"


# --------------------------------------------------------------------------- #
# 数据库安全
# --------------------------------------------------------------------------- #


def test_compose_does_not_expose_db_port_to_host():
    """postgres 端口绝不能映射到宿主机。

    映射出去等于数据库直接暴露在公网上，任何扫到 5432 的人都能试密码。
    """
    assert "ports" not in _compose()["services"]["postgres"]


def test_api_does_not_expose_port_directly():
    """api 只通过 nginx 对外。自己映射端口等于绕过了 HTTPS 与限流。"""
    assert "ports" not in _compose()["services"]["api"]


def test_db_credentials_come_from_env():
    """数据库密码不能硬编码在 compose 里。"""
    raw = _read("docker-compose.yml")
    for secret in ("POSTGRES_PASSWORD: coc", "PASSWORD: coc123"):
        assert secret not in raw


# --------------------------------------------------------------------------- #
# 单副本（Global Constraints）
# --------------------------------------------------------------------------- #


def test_dockerfile_uses_single_worker():
    """``--workers 1`` 是硬性要求。

    多 worker = 多个令牌桶 + 多个 APScheduler。令牌桶不是共享的，实际速率会
    翻 N 倍直接被 Supercell 限流；调度器也会重复跑同一个 job。
    """
    dockerfile = _read("Dockerfile")
    assert "--workers 1" in dockerfile, "CMD 必须固定 --workers 1"
    assert re.search(r"--workers\s+(?!1\b)\d+", dockerfile) is None, (
        "不允许出现 --workers N（N != 1）"
    )


def test_compose_does_not_override_workers():
    assert "workers" not in _read("docker-compose.yml").lower()


def test_app_role_defaults_to_all():
    """单副本一体：默认 all，同时服务 HTTP 与采集。"""
    assert "APP_ROLE" in _read("docker-compose.yml")


# --------------------------------------------------------------------------- #
# nginx
# --------------------------------------------------------------------------- #


def test_nginx_proxies_api_and_media():
    conf = _read("deploy/nginx.conf")
    assert "location /api/" in conf
    assert "location /media/" in conf


def test_nginx_forwards_x_forwarded_for():
    """**限流依赖这个头**。

    反代后 ``request.client.host`` 永远是 127.0.0.1，不透传就是全网共用一个桶 ——
    一个人刷爆，所有人 429。
    """
    conf = _read("deploy/nginx.conf")
    assert "X-Forwarded-For" in conf
    assert "$proxy_add_x_forwarded_for" in conf


def test_nginx_proxies_admin():
    """后台要经 nginx 暴露，否则只能从容器内访问。"""
    assert "location /admin/" in _read("deploy/nginx.conf")


def test_nginx_serves_media_as_read_only_alias():
    """媒体目录用 alias 而不是 root —— root 会被路径穿越。"""
    conf = _read("deploy/nginx.conf")
    assert "alias" in conf
    assert "autoindex off" in conf, "目录列举会把投稿图片全公开"


def test_nginx_enforces_https_redirect():
    """HTTP 必须 301 到 HTTPS —— 小程序只接受 HTTPS 域名。"""
    assert "return 301 https://" in _read("deploy/nginx.conf")


def test_nginx_sets_client_max_body_size_for_uploads():
    """默认 1m 太小，投稿图片会被截断成损坏文件。"""
    assert "client_max_body_size" in _read("deploy/nginx.conf")


# --------------------------------------------------------------------------- #
# 密钥
# --------------------------------------------------------------------------- #


def test_env_example_contains_no_real_secret():
    """示例文件里敏感项必须是空值。

    一旦填了真实值并提交，密钥就进了 git 历史 —— 之后再删文件也删不掉。
    """
    for line in _read(".env.example").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key in {
            "COC_API_TOKEN",
            "ADMIN_PASSWORD",
            "ADMIN_SECRET_KEY",
            "DATABASE_URL",
        }:
            assert value == "", f"示例文件不得含真实值: {stripped}"


def test_env_is_gitignored():
    """.env 绝不能进版本库。"""
    assert ".env" in _read(".gitignore")


def test_deployment_doc_warns_about_mini_program_domain():
    """必须提醒在小程序后台配 request 合法域名。

    漏掉这一步小程序端完全调不通，而且报错只说"不在合法域名列表里"，
    排查方向很容易跑偏到代码上。
    """
    doc = _read("docs/deployment.md")
    assert "合法域名" in doc


def test_deployment_doc_mentions_import_game_data():
    """上线清单必须包含导入升级数据 —— 空库的升级接口返回空列表。"""
    assert "import-game-data" in _read("docs/deployment.md")


# --------------------------------------------------------------------------- #
# 健康检查
# --------------------------------------------------------------------------- #


def test_compose_uses_readyz_for_api_healthcheck():
    """用 /readyz 而不是 /healthz。

    /healthz 只证明进程活着，DB 挂了它照样 200 —— 编排器会把流量继续打进来。
    """
    compose = _compose()
    healthcheck = compose["services"]["api"].get("healthcheck", {})
    assert "/readyz" in str(healthcheck.get("test", ""))


def test_nginx_conf_is_mounted_as_a_template_not_directly():
    """nginx 配置必须经官方镜像的 templates 机制，不能直接挂进 conf.d。

    官方 nginx 镜像**只对** ``/etc/nginx/templates/*.template`` 做变量替换；
    直接挂到 ``/etc/nginx/conf.d/`` 的话 ``${SERVER_NAME}`` 原样保留，
    nginx 解析到 ``server_name ${SERVER_NAME}`` 直接起不来 ——
    而这个错误本机测不出来（没装 docker），上线第一次 ``compose up`` 才炸。
    """
    raw = _read("docker-compose.yml")
    assert "/etc/nginx/templates/" in raw, "nginx 配置必须挂载为模板"
    assert ".template" in raw
    # 只看配置行，不看注释 —— 注释里提到 conf.d 是解释为什么不能这么做
    directives = "\n".join(
        line for line in raw.splitlines() if not line.strip().startswith("#")
    )
    assert "/etc/nginx/conf.d/" not in directives, "不能直接挂到 conf.d"


def test_nginx_conf_uses_the_variable_that_actually_exists():
    """模板里的变量名必须是 nginx 容器里**真实存在的**环境变量。

    compose 给 nginx 注入的是 ``SERVER_NAME``（值来自 PUBLIC_BASE_URL）。
    模板里若写 ``${PUBLIC_BASE_URL}``，envsubst 找不到这个名字就替换成空串，
    ``server_name`` 变成空 —— 报错藏在 nginx 的启动日志里，很难找。
    """
    conf = _read("deploy/nginx.conf")
    directives = "\n".join(
        line for line in conf.splitlines() if not line.strip().startswith("#")
    )
    assert "${SERVER_NAME}" in directives
    assert "PUBLIC_BASE_URL" not in directives, (
        "compose 注入的变量名是 SERVER_NAME，不是 PUBLIC_BASE_URL"
    )


def test_nginx_upstream_points_at_the_api_service():
    """nginx 必须指向 compose 里的服务名，不能写 localhost。

    ``upstream`` 块里可以写别名（这里是 ``coc_api``），但它 resolve 的那个
    ``server`` 行必须是服务名 —— 容器里的 localhost 是 nginx 自己。
    """
    conf = _read("deploy/nginx.conf")
    assert re.search(r"server\s+api:8000", conf), "upstream 必须指向 api 服务"
    # 只看配置行，不看注释 —— 注释里提到 localhost 是解释，不是配置
    directives = "\n".join(
        line for line in conf.splitlines() if not line.strip().startswith("#")
    )
    assert "localhost" not in directives, (
        "容器里的 localhost 是自己，不是 api"
    )


# --------------------------------------------------------------------------- #
# 构建速度（部署体验）
# --------------------------------------------------------------------------- #


def test_dockerfile_does_not_disable_pip_cache():
    """``PIP_NO_CACHE_DIR=1`` 会把 pip 的下载缓存整个关掉。

    后果不是"慢一点"：每次重建镜像都要重下全部依赖 —— 实测一次 **22 分钟**，
    几乎全耗在下载上，于是改一行代码也要等十几分钟。
    """
    dockerfile = _read("Dockerfile")
    # 只看配置行，不看注释 —— 注释里提到它是在解释"为什么不能这么写"
    directives = "\n".join(
        line for line in dockerfile.splitlines() if not line.strip().startswith("#")
    )
    assert re.search(r"PIP_NO_CACHE_DIR\s*[=:]\s*1", directives) is None, (
        "不要设 PIP_NO_CACHE_DIR=1：pip 缓存被关掉后每次重建都重下全量依赖"
    )


def test_dockerfile_uses_buildkit_cache_mount_for_pip():
    """pip 的下载要用 BuildKit cache mount 缓存住。

    cache mount 的内容**不进镜像层**，只留在 BuildKit 缓存里：第一次构建下全量，
    之后每次重建只花"缓存命中"的时间（几十秒）。需要 BuildKit（Docker 23+ 默认启用）。
    """
    dockerfile = _read("Dockerfile")
    assert "--mount=type=cache,target=/root/.cache/pip" in dockerfile, (
        "pip install 必须挂 BuildKit cache mount："
        "--mount=type=cache,target=/root/.cache/pip"
    )


def test_dockerfile_installs_dependencies_before_copying_source():
    """依赖安装层不能被源码改动打穿。

    ``COPY app ./app`` 若出现在 ``pip install`` 之前，改一行代码就会让
    "建 venv + 装全量依赖" 整层失效 —— 每次重建多花几分钟，且与改动无关。
    判定就是**源码拷贝必须在依赖安装之后**；依赖清单的唯一来源是 pyproject.toml，
    不允许另加 requirements.txt（两份清单会漂移）。
    """
    dockerfile = _read("Dockerfile")
    assert "pip install -r /tmp/requirements.txt" in dockerfile, (
        "依赖应从 pyproject.toml 抽出的清单安装（未引入 requirements.txt）"
    )
    assert not (ROOT / "requirements.txt").exists(), (
        "不要引入 requirements.txt：依赖的唯一来源是 pyproject.toml"
    )
    # 只看指令行，不看注释 —— 注释里讨论这段顺序时会原样写出这两个字符串
    directives = "\n".join(
        line for line in dockerfile.splitlines() if not line.strip().startswith("#")
    )
    assert directives.index("COPY app ./app") > directives.index(
        "pip install -r /tmp/requirements.txt"
    ), "COPY app 必须排在依赖安装之后，否则改代码会重装全部依赖"
    assert "pip install --no-deps ." in directives, (
        "应用自身必须用 --no-deps 安装：依赖已经装好，重装依赖既慢又可能改变版本"
    )


# --------------------------------------------------------------------------- #
# 运维脚本
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("script", ["deploy/certbot-renew.sh", "deploy/backup.sh"])
def test_scripts_are_executable_bash(script):
    body = _read(script)
    assert body.startswith("#!"), f"{script} 缺少 shebang"
    assert "bash" in body.splitlines()[0]


def test_backup_script_prunes_old_backups():
    """不清理的话备份会把磁盘吃满，最后连数据库都写不进去。"""
    assert "-mtime" in _read("deploy/backup.sh")


def test_backup_script_dumps_the_database():
    body = _read("deploy/backup.sh")
    assert "pg_dump" in body