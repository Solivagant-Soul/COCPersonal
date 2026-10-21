#!/usr/bin/env bash
#
# COCPersonal 部署入口：从 .env 的 PUBLIC_BASE_URL 推导**宿主机端口**，再转交 docker compose。
#
# 为什么需要这个脚本
# ------------------
# docker compose 只支持整值插值（`${VAR}`），**没有子串/正则运算**，所以没法在
# `ports:` 里写「从 PUBLIC_BASE_URL 里抠出端口」。硬编码 `"80:80"` 的坏处是：
# 改 `.env` 里的 PUBLIC_BASE_URL 不会改端口，两边悄悄不一致（媒体绝对 URL 指向 80，
# 实际服务在 7788，投稿图片全裂）。
#
# compose 的 `ports` 写成 `"${WEB_PORT:-80}:${WEB_CONTAINER_PORT:-80}"`：两侧端口由
# 本脚本导出，直接用 `docker compose`（不经本脚本）时回落到 80:80 —— 老行为不变。
#
# 用法
# ----
#   ./deploy/compose.sh up -d            # 等价于 docker compose up -d，端口按 PUBLIC_BASE_URL
#   ./deploy/compose.sh logs -f web
#   ./deploy/compose.sh ps
#   ./deploy/compose.sh --print-port      # 只打印宿主机端口，不碰 docker（排障/测试用）
#   ./deploy/compose.sh --print-ports     # 打印两侧：host=<端口> container=<端口>
#
# 端口规则
# --------
#   http://host:7788  ->  宿主机 7788 -> 容器 80
#   http://host        ->  宿主机 80   -> 容器 80
#   https://host:8443  ->  宿主机 8443 -> 容器 443
#   https://host       ->  宿主机 443  -> 容器 443
#
# **容器侧端口跟着协议走**（http→80 / https→443），因为容器内 nginx 监听的端口
# 必须与对外协议匹配：把 https 流量转到容器的 80 端口，nginx 会用**明文**应答，
# 浏览器直接报 TLS 握手失败 —— 而容器日志里看不出任何异常。
#
# 代价：走 https 时，容器内必须真的有 443 server 块。`deploy/nginx.conf` 末尾那段
# 443 ssl 是**注释掉的**（默认 HTTP-only），所以启用 https 前要先按
# docs/deployment.md §9 把它打开 —— 否则宿主机连上 443 端口会被拒绝
# （connection refused），是**响亮的失败**，不会静默降级成明文。
#
# 覆盖与排查
# ----------
#   PUBLIC_BASE_URL  环境变量优先于 .env 文件（与 compose 自身的优先级一致）。
#   ENV_FILE         换一个 .env 文件路径（默认 <仓库根>/.env）。
#   WEB_PORT         不用设；本脚本每次都从 PUBLIC_BASE_URL 重算，避免两边不一致。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${ROOT_DIR}/.env}"

# --------------------------------------------------------------------------- #
# 从 .env 取一个键的原始值
#
# 只做三件事：去掉 `export ` 前缀、剥掉一层引号、rstrip。
# **不做变量插值**（.env 里的 ${OTHER} 保持原样，与 compose 的行为有意区分：
# 端口推导必须拿到字面值，不能被二次插值改掉）。
# --------------------------------------------------------------------------- #
read_env_value() {
    local key="$1" line value
    [ -f "${ENV_FILE}" ] || return 1
    line="$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}=" "${ENV_FILE}" | tail -n 1)" || return 1
    [ -n "${line}" ] || return 1
    value="${line#*=}"
    # 去尾部注释（` #` 之后），但不动 URL 里的 `://` 与 `%`
    value="${value%%[[:space:]]#*}"
    # rstrip 空白
    value="${value%"${value##*[![:space:]]}"}"
    case "${value}" in
        \"*\") value="${value#\"}"; value="${value%\"}" ;;
        \'*\') value="${value#\'}"; value="${value%\'}" ;;
    esac
    [ -n "${value}" ] || return 1
    printf '%s' "${value}"
}

# --------------------------------------------------------------------------- #
# 解析 PUBLIC_BASE_URL -> 宿主机端口
# --------------------------------------------------------------------------- #
derive_port() {
    local base="$1" scheme rest hostport port ipv6_tail

    case "${base}" in
        *://*) ;;
        *)
            echo "错误：PUBLIC_BASE_URL 必须带协议（如 http://1.2.3.4:7788），当前是 [${base}]" >&2
            return 1
            ;;
    esac

    scheme="${base%%://*}"
    case "${scheme}" in
        http|https) ;;
        *)
            echo "错误：PUBLIC_BASE_URL 的协议只能是 http/https，当前是 [${scheme}]" >&2
            return 1
            ;;
    esac

    rest="${base#*://}"
    rest="${rest%%#*}"      # 去 fragment
    rest="${rest%%\?*}"     # 去查询串
    rest="${rest%%/*}"      # 去路径
    hostport="${rest##*@}"  # 去 userinfo（http://user:pass@host:port）

    if [ -z "${hostport}" ]; then
        echo "错误：PUBLIC_BASE_URL 里没有主机名：[${base}]" >&2
        return 1
    fi

    if [ "${hostport#\[}" != "${hostport}" ]; then
        # IPv6 字面量：[::1] 或 [::1]:7788 —— 里面的冒号不能当端口分隔符
        ipv6_tail="${hostport#*\]}"       # ] 之后的部分
        if [ "${ipv6_tail}" = "${hostport}" ]; then
            # 没有闭合的 ]，格式非法
            echo "错误：PUBLIC_BASE_URL 的 IPv6 地址格式非法：[${base}]" >&2
            return 1
        fi
        case "${ipv6_tail}" in
            "")   port="" ;;
            :*)   port="${ipv6_tail#:}"
                    case "${port}" in
                        ''|*[!0-9]*)
                            echo "错误：无法从 PUBLIC_BASE_URL 解析出端口：[${base}]" >&2
                            return 1
                            ;;
                    esac
                    ;;
            *)
                echo "错误：无法从 PUBLIC_BASE_URL 解析出端口：[${base}]" >&2
                return 1
                ;;
        esac
    else
        case "${hostport}" in
            *:*)
                port="${hostport##*:}"
                case "${port}" in
                    ''|*[!0-9]*)
                        echo "错误：无法从 PUBLIC_BASE_URL 解析出端口：[${base}]" >&2
                        return 1
                        ;;
                esac
                ;;
            *) port="" ;;
        esac
    fi

    if [ -z "${port}" ]; then
        # 没写端口 → 用协议的默认端口
        case "${scheme}" in
            https*) port=443 ;;
            http*)  port=80 ;;
        esac
    fi

    # 端口范围校验（1-65535）。越界的值放行到 docker 会报一个难懂的错，
    # 这里直接说人话。
    if [ "${port}" -lt 1 ] || [ "${port}" -gt 65535 ]; then
        echo "错误：PUBLIC_BASE_URL 解析出的端口越界（${port}，应为 1-65535）：[${base}]" >&2
        return 1
    fi

    printf '%s' "${port}"
}

# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
base_url="${PUBLIC_BASE_URL:-}"
if [ -z "${base_url}" ]; then
    base_url="$(read_env_value PUBLIC_BASE_URL || true)"
fi

if [ -z "${base_url}" ]; then
    echo "错误：PUBLIC_BASE_URL 未设置，且在 ${ENV_FILE} 里也没找到。" >&2
    echo "      它是必填项，且决定对外端口。参考 .env.example 填写，例如：" >&2
    echo "      PUBLIC_BASE_URL=http://1.2.3.4:7788" >&2
    exit 1
fi

host_port="$(derive_port "${base_url}")"

# 容器侧端口跟着协议走：http→80（nginx 的明文 server），https→443（TLS server）。
# 两者不一致 = 浏览器 TLS 握手失败，且容器日志里看不出异常。
case "${base_url}" in
    https://*) container_port=443 ;;
    *)         container_port=80 ;;
esac

if [ "${1:-}" = "--print-port" ]; then
    printf '%s\n' "${host_port}"
    exit 0
fi

if [ "${1:-}" = "--print-ports" ]; then
    printf 'host=%s container=%s\n' "${host_port}" "${container_port}"
    exit 0
fi

export WEB_PORT="${host_port}"
export WEB_CONTAINER_PORT="${container_port}"

# cd 到仓库根：compose 里的相对路径（./deploy/nginx.conf）按项目目录解析，
# 且 compose 默认从项目目录读 .env
cd "${ROOT_DIR}"
exec docker compose --project-directory "${ROOT_DIR}" "$@"
