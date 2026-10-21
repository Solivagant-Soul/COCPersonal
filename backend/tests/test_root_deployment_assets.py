"""仓库**根级**部署资产（`docker-compose.yml` / `deploy/compose.sh`）的校验。

与 `test_deployment_config.py` 的分工：那一份管 `backend/` 自己的部署栈
（`backend/docker-compose.yml` + `backend/deploy/`），这一份管仓库根的 COCPersonal
部署栈（根 `docker-compose.yml` + 根 `deploy/`）。

守的是一条具体的坑：**对外端口必须由 `.env` 的 `PUBLIC_BASE_URL` 决定**。
端口是 URL 的一部分，而 docker compose 只支持整值 `${VAR}` 插值、**没有子串运算**，
所以这个映射必须由 `deploy/compose.sh` 完成。若哪天有人把 `ports:` 改回硬编码
`"80:80"`，`.env` 里的端口就会被无声忽略 —— 媒体绝对 URL 指向 80、实际服务在 7788，
投稿图片全裂，且没有任何报错。所以这里把「compose 必须用变量、脚本必须能解析端口」
变成会失败的测试。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
COMPOSE_SCRIPT = REPO_ROOT / "deploy" / "compose.sh"


# --------------------------------------------------------------------------- #
# bash 定位
#
# Windows 上 PATH 里的 bash 是 WSL 转发桩（未安装 WSL 时会报
# `execvpe(/bin/bash) failed`），Git Bash 才是唯一可用的。找不到就跳过，
# 不让「本机没装 bash」变成测试失败 —— Linux CI 上照跑。
# --------------------------------------------------------------------------- #
def _find_bash() -> str | None:
    if os.name != "nt":
        return shutil.which("bash")
    candidates = [
        os.environ.get("GIT_BASH"),
        r"D:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\bin\bash.exe",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return shutil.which("bash")


BASH = _find_bash()
requires_bash = pytest.mark.skipif(BASH is None, reason="本机没有可用的 bash")


def _compose() -> dict:
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# compose：ports 必须是变量，不能硬编码
# --------------------------------------------------------------------------- #


def test_web_port_is_not_hardcoded():
    """web 的宿主机端口不能写死 —— 写死了 `.env` 的端口就被无声忽略。"""
    ports = _compose()["services"]["web"]["ports"]
    assert ports == ["${WEB_PORT:-80}:${WEB_CONTAINER_PORT:-80}"], (
        f"web 的 ports 必须是 ${{WEB_PORT:-80}}:${{WEB_CONTAINER_PORT:-80}}"
        f"（两侧都由 deploy/compose.sh 从 PUBLIC_BASE_URL 推导），实际是 {ports}"
    )


def test_container_side_port_is_variable_not_hardcoded():
    """容器侧端口也必须是变量 —— 走 https 时要转到容器的 443。

    写死 80 的话，https 流量会被转到明文端口，浏览器报 TLS 握手失败，
    而容器日志里看不出任何异常。
    """
    ports = _compose()["services"]["web"]["ports"]
    assert all("WEB_CONTAINER_PORT" in p for p in ports), (
        f"容器侧端口必须用 ${{WEB_CONTAINER_PORT}}，实际是 {ports}"
    )


def test_only_web_exposes_ports():
    """api / postgres 不得对外暴露（部署铁律 #2）。"""
    services = _compose()["services"]
    assert "ports" not in services["api"]
    assert "ports" not in services["postgres"]


# --------------------------------------------------------------------------- #
# deploy/compose.sh：存在 + 可执行
# --------------------------------------------------------------------------- #


def test_compose_script_exists():
    assert COMPOSE_SCRIPT.exists(), "缺少 deploy/compose.sh"


def test_compose_script_is_executable_in_git():
    """git 里必须带 +x —— 服务器 clone 下来直接 `./deploy/compose.sh up -d` 会 Permission denied。"""
    mode = subprocess.run(
        ["git", "ls-files", "-s", "deploy/compose.sh"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout.strip()
    assert mode.startswith("100755"), f"deploy/compose.sh 在 git 里不是可执行位（{mode}）"


# --------------------------------------------------------------------------- #
# 端口推导
# --------------------------------------------------------------------------- #


def _run_script(
    env_file: Path | None = None,
    env_overrides: dict | None = None,
    flag: str = "--print-port",
) -> str:
    env = dict(os.environ)
    env.pop("PUBLIC_BASE_URL", None)  # 默认从 .env 文件读
    env.pop("WEB_PORT", None)
    env.pop("WEB_CONTAINER_PORT", None)
    if env_file is not None:
        env["ENV_FILE"] = str(env_file)
    if env_overrides:
        env.update(env_overrides)
    proc = subprocess.run(
        [BASH, str(COMPOSE_SCRIPT), flag],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    assert proc.returncode == 0, f"脚本退出码 {proc.returncode}：{proc.stderr}"
    return proc.stdout.strip()


@requires_bash
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://1.2.3.4:7788", "7788"),
        ("https://example.com:8443", "8443"),
        ("http://1.2.3.4", "80"),  # http 默认端口
        ("https://example.com", "443"),  # https 默认端口
        ("http://1.2.3.4:7788/", "7788"),  # 带路径
        ("http://1.2.3.4:7788/media", "7788"),
        ("http://1.2.3.4:7788?x=1", "7788"),
        ("http://user:pass@1.2.3.4:7788", "7788"),  # userinfo
        ("http://[::1]:7788", "7788"),  # IPv6
    ],
)
def test_port_derived_from_public_base_url(url: str, expected: str, tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"PUBLIC_BASE_URL={url}\n", encoding="utf-8")
    assert _run_script(env_file) == expected


@requires_bash
def test_port_read_from_quoted_value(tmp_path: Path):
    """.env 里加引号很常见，端口不能因此解析不出来。"""
    env_file = tmp_path / ".env"
    env_file.write_text('PUBLIC_BASE_URL="http://1.2.3.4:7788"\n', encoding="utf-8")
    assert _run_script(env_file) == "7788"


@requires_bash
@pytest.mark.parametrize(
    ("url", "host_port", "container_port"),
    [
        # http -> 容器明文端口 80
        ("http://1.2.3.4:7788", "7788", "80"),
        ("http://1.2.3.4", "80", "80"),
        # https -> 容器 TLS 端口 443。两侧不一致 = 浏览器 TLS 握手失败，
        # 且容器日志里看不出任何异常，所以这里钉死。
        ("https://example.com:8443", "8443", "443"),
        ("https://example.com", "443", "443"),
    ],
)
def test_container_port_follows_scheme(
    url: str, host_port: str, container_port: str, tmp_path: Path
):
    env_file = tmp_path / ".env"
    env_file.write_text(f"PUBLIC_BASE_URL={url}\n", encoding="utf-8")
    out = _run_script(env_file, flag="--print-ports")
    assert out == f"host={host_port} container={container_port}"


@requires_bash
def test_env_var_overrides_env_file(tmp_path: Path):
    """环境变量优先于 .env 文件（与 compose 自身优先级一致）。"""
    env_file = tmp_path / ".env"
    env_file.write_text("PUBLIC_BASE_URL=http://1.2.3.4:7788\n", encoding="utf-8")
    assert _run_script(env_file, {"PUBLIC_BASE_URL": "http://1.2.3.4:9999"}) == "9999"


@requires_bash
def test_missing_public_base_url_fails_loudly(tmp_path: Path):
    """缺 PUBLIC_BASE_URL 必须报错退出 —— 不能静默回落到 80。"""
    env_file = tmp_path / ".env"
    env_file.write_text("POSTGRES_PASSWORD=x\n", encoding="utf-8")
    env = dict(os.environ)
    env.pop("PUBLIC_BASE_URL", None)
    env["ENV_FILE"] = str(env_file)
    proc = subprocess.run(
        [BASH, str(COMPOSE_SCRIPT), "--print-port"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    assert proc.returncode != 0
    assert "PUBLIC_BASE_URL" in proc.stderr


@requires_bash
def test_url_without_scheme_fails_loudly(tmp_path: Path):
    """没带协议的 PUBLIC_BASE_URL 必须报错（compose 里 PUBLIC_BASE_URL 同样要求带协议）。"""
    env_file = tmp_path / ".env"
    env_file.write_text("PUBLIC_BASE_URL=1.2.3.4:7788\n", encoding="utf-8")
    env = dict(os.environ)
    env.pop("PUBLIC_BASE_URL", None)
    env["ENV_FILE"] = str(env_file)
    proc = subprocess.run(
        [BASH, str(COMPOSE_SCRIPT), "--print-port"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    assert proc.returncode != 0
    assert "协议" in proc.stderr
