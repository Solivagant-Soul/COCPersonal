# syntax=docker/dockerfile:1
#
# 单副本部署（Global Constraints）。**--workers 1 是硬性要求，不是可调项。**
#
# 为什么不能加 worker：
#   1. 令牌桶（MemoryRateLimiter）是**进程内**的。多 worker = 多个令牌桶，
#      对 Supercell 的实际速率翻 N 倍，直接被限流。
#   2. APScheduler 同理。多 worker 会让同一个采集 job 跑 N 遍。
#   3. 读时旁路缓存也是进程内的，多副本之间不共享。
#
# 要横向扩展得先把限流、缓存、调度都换成共享实现（Redis / 独立采集进程）。

# --------------------------------------------------------------------------- #
# builder：装依赖
# --------------------------------------------------------------------------- #
FROM python:3.12-slim AS builder

# **不要设 PIP_NO_CACHE_DIR=1** —— 它会把 pip 的下载缓存整个关掉，
# 于是每次重建镜像都要重下全部依赖（实测一次 22 分钟，几乎全耗在下载上）。
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# SQLAlchemy 必须 <2.1（见 AGENTS.md）
COPY pyproject.toml README.md ./
COPY app ./app

# cache mount：pip 的下载缓存留在 BuildKit 缓存里，**不进镜像层**。
# 第一次构建仍然要下全量（十几分钟，取决于到 PyPI 的带宽），
# 之后每次重建只要几十秒 —— 改代码不用再等一遍下载。
#
# 需要 BuildKit（Docker 23+ 默认启用）。若报 "--mount option requires BuildKit"，
# 用 DOCKER_BUILDKIT=1 docker build ... 或升级 Docker。
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install .


# --------------------------------------------------------------------------- #
# runtime：只带运行所需
# --------------------------------------------------------------------------- #
FROM python:3.12-slim

# curl 供 healthcheck 用；libpq5 是 asyncpg 的运行时依赖
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 非 root 运行。媒体目录归这个用户所有，投稿上传才能落盘。
RUN useradd --create-home --uid 10001 coc \
    && mkdir -p /data/media \
    && chown -R coc:coc /data
USER coc

WORKDIR /app
COPY alembic.ini ./
COPY migrations ./migrations

EXPOSE 8000

# 单副本一体：同进程跑 API 与采集调度器。
# --workers 1 见文件头的说明，不要改。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]