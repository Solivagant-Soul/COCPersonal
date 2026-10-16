# coc-backend

COC 微信小程序后端（FastAPI + SQLAlchemy 2.0 async + PostgreSQL），从同级 `COCBack` 全量搬入。
一期做查询、我的、投稿；二期做阵容、阵型；爬虫另立项目。

本目录同时被仓库根的 Docker 组合栈（`../docker-compose.yml`）以 `build: ./backend` 构建成 `api` 镜像，
故 `Dockerfile` 里的 `COPY pyproject.toml README.md ./` 依赖本文件存在——不要删。

## 测试

```powershell
python -m pytest -q                                  # 全量测试（默认即可用，无需 venv）
python -m pytest tests/coc/ -q                       # 单个目录
python -m pytest tests/db/test_dim_models.py::test_x # 单个用例
```

数据库测试前置：本机需 PostgreSQL 在 `127.0.0.1:5433`（`C:\pgportable` 免安装实例）。
`tests/conftest.py` 会自动跑 `alembic upgrade head`。

## 配置

本地未建 `.env` 时 alembic / `app.cli` 会直接失败（不走 conftest）。做法：

```powershell
Copy-Item .env.example .env
```

再填值。该文件已被忽略，不入库。

更多环境陷阱与硬约束见 `AGENTS.md`。
