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

# **依赖层只依赖清单，不依赖源码。**
# 把 `COPY app ./app` 放在 pip install 之前的话，改一行代码就会让这一层失效、
# 整套依赖重装一遍 —— 实测线上每次多花几分钟，而这几分钟与代码改动毫无关系。
# 依赖列表直接从 pyproject.toml 抽（**唯一来源**），不另维护 requirements.txt：
# 两份清单必然漂移，而漂移只会在重建镜像时才暴露。
RUN python - > /tmp/requirements.txt <<'PY'
import pathlib
import tomllib

project = tomllib.loads(pathlib.Path("pyproject.toml").read_text(encoding="utf-8"))
print("\n".join(project["project"]["dependencies"]))
PY

# cache mount：pip 的下载缓存留在 BuildKit 缓存里，**不进镜像层**。
# 第一次构建仍然要下全量（十几分钟，取决于到 PyPI 的带宽），
# 之后每次重建只要几十秒 —— 改代码不用再等一遍下载。
#
# 需要 BuildKit（Docker 23+ 默认启用）。若报 "--mount option requires BuildKit"，
# 用 DOCKER_BUILDKIT=1 docker build ... 或升级 Docker。上面的 heredoc 同样要求 BuildKit。
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r /tmp/requirements.txt

# 应用自身单独装：`--no-deps` 保证不动依赖层，且**只有这一层依赖源码**。
# 只改代码时上面两层全部命中缓存，重建实测十几秒。
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/pip \
    /opt/venv/bin/pip install --no-deps .


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