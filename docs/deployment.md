# COCPersonal 部署文档（Docker Compose，Linux 单机）

> 适用对象：在一台**全新的 Linux 服务器**上，把 `web`(nginx) + `api`(FastAPI) +
> `postgres` 三容器栈从零跑到「浏览器能查玩家/部落、能看排行榜、能进后台」。
>
> ⚠️ **诚实声明（必读）**：本仓库开发机没有 Docker（虚拟化在固件层关闭，见
> `AGENTS.md`），部署资产只做到**静态校验**（`backend/tests/test_deployment_config.py`
> 的 69 条断言）与「同代码 × 本机 uvicorn + vite」的 HTTP 实测。本文中所有命令因此
> 分两档标注：
>
> - **【已验证】** —— 命令与预期输出在本机同代码路径实跑过；
> - **【首跑核对】** —— 第一次真实 `docker compose up` 时按 §10 清单逐条核对，
>   有出入以实际输出为准，并回填本文。
>
> **与 `backend/docs/deployment.md` 的关系**：那份是 COCBack（小程序版）的部署清单，
> 对本仓库**不适用**，差异一列就够踩坑了：
>
> 1. 其第 8 步「小程序合法域名」不存在 —— 本仓库是网页，不是小程序；
> 2. 它假设 compose 里有 `certbot` 服务、nginx 服务名是 `nginx` —— 本仓库 compose
>    没有 certbot 服务，对外服务名是 **`web`**（`docker compose logs -f web`）；
> 3. 它要求 `PUBLIC_BASE_URL` 填**不带协议的备案域名**（当 nginx `SERVER_NAME` 用）——
>    本仓库必须**带协议**（如 `http://<IP>`，拼媒体绝对 URL 用），nginx 的
>    `server_name` 恒为 `_`（静态配置，见 `deploy/nginx.conf`）；
> 4. 它的备份/续期脚本路径是 `/opt/coc` —— 本仓库建议克隆到 `/opt/cocpersonal`，
>    `backup.sh` 已适配，`certbot-renew.sh` 是遗留参考（见 §9 的 HTTPS 实操）。

## 0. 架构与铁律（先读这个再动手）

一句话：`web` 托管 Vue 构建产物，把 `/api`、`/admin`、`/media`、`/healthz`、`/readyz`
反代给 `api`；`api` 连 `postgres`，并内置 APScheduler 定时采集。

| 容器 | 镜像来源 | 对外端口 | 数据落点 |
| --- | --- | --- | --- |
| web | `frontend/Dockerfile`（node:24-alpine 构建 → nginx:1.27-alpine） | `PUBLIC_BASE_URL` 里写的那个端口（默认 **80**） | 无状态 |
| api | `backend/Dockerfile`（python:3.12-slim，非 root 运行） | 无（内部 8000） | `media` 卷（读写） |
| postgres | postgres:16-alpine | 无（内部 5432） | `pgdata` 命名卷 |

四条铁律（都有代码注释背书，别"优化"掉）：

1. **api 的 `--workers 1` 是硬约束**（`backend/Dockerfile` 文件头）——令牌桶、读时
   旁路缓存、APScheduler 全是进程内的；多 worker = 对 Supercell 速率翻倍 + 采集任务
   重复执行。
2. **只有 web 暴露端口**。别给 api/postgres 加 `ports:`——那是部署配置测试的断言内容。
3. **对 Supercell 的速率默认 8 次/秒**（`COC_RATE_LIMIT`）。走 RoyaleAPI 共享代理时
   **不要调高**（§6）。
4. **`X-Forwarded-For` 必须透传**（`deploy/nginx.conf` 已配好）——对外限流按真实
   客户端 IP 计数，不透传的话全网共用一个桶，一人 429 全站跟着 429。

## 1. 前置条件

| 项 | 要求 | 说明 |
| --- | --- | --- |
| 服务器 | Linux x86_64，2 核 4G 起 | 资源大头是 postgres 与前端构建 |
| Docker | 24+，`docker compose version` 可用 | **v2 语法**，别用旧 docker-compose v1 |
| 防火墙 | 放行 `PUBLIC_BASE_URL` 里写的那个端口（默认 80；启用 HTTPS 后是 443） | api/postgres 无需对外 |
| 出网 | `registry-1.docker.io`（拉镜像）、`registry.npmjs.org`（导入升级数据） | 夹具模式下**不需要** Supercell 网络 |
| 域名（可选） | 已解析 + 备案 | 只在启用 HTTPS（§9）时需要 |
| Supercell Token（可选） | 不填也能完整跑通整站 | 不填 = 夹具模式（§5） |

```bash
cd /opt && mkdir cocpersonal && cd cocpersonal
git clone https://github.com/Solivagant-Soul/COCPersonal.git .
docker compose version    # 【首跑核对】能打印 v2 版本信息
```

## 2. 配 `.env`（唯一需要动脑的一步）

```bash
cp .env.example .env
openssl rand -base64 36   # 跑三次：POSTGRES_PASSWORD / ADMIN_PASSWORD / ADMIN_SECRET_KEY
```

**必填 5 项**（compose 用 `${VAR:?}` 保护：漏一项，`up` 时直接报错并点出变量名，
不存在"带空密码上线"的可能）：

| 变量 | 填什么 | 说明与坑 |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | 强密码 | 库虽在内网，但这是最后一道门 |
| `ADMIN_USERNAME` | 用户名 | 后台 http://IP/admin/ 的登录名 |
| `ADMIN_PASSWORD` | 强密码 | 凭据只从环境变量读，**不入库、无 create-admin 命令** |
| `ADMIN_SECRET_KEY` | 随机串 ≥43 字符 | session cookie 签名密钥；泄露 = 任何人可伪造管理员会话 |
| `PUBLIC_BASE_URL` | `http://<服务器IP>` **必须带协议** | 拼投稿/媒体图片的**绝对 URL** 用。**与 COCBack 文档相反**。上 HTTPS 后改 `https://<域名>`。**同时决定对外端口**（见下方「端口由 PUBLIC_BASE_URL 决定」） |

可选变量（`.env.example` 里的默认值可直接用）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `POSTGRES_DB` / `POSTGRES_USER` | `coc` / `coc` | 改了的话 §4/§9 的 psql 命令也要跟着改 |
| `COC_API_TOKEN` | 空 | **空 = 夹具模式**；拿到 Token 只填这里，绝不入 git |
| `COC_BASE_URL` | 空（官方直连） | 服务器无静态 IP 时填 `https://cocproxy.royaleapi.dev/v1`（§6） |
| `COC_RATE_LIMIT` | 8 | 上游令牌桶（次/秒），走代理**不要调高** |
| `RATE_LIMIT_PER_MINUTE` | 60 | 对外每 IP 每分钟；`/healthz`、`/readyz` 不计桶 |
| `APP_ROLE` | `all` | 单机部署固定 `all`；`api`/`collector` 是拆进程预留位 |
| `LOG_LEVEL` | `INFO` | |
| `WARREPORT_BASE_URL` | `https://api.warreport.app` | War Report 赛季榜 / 阵容的上游；**不是密钥**，指向测试假上游时改这里（§12） |
| `WARREPORT_TIMEOUT` | `15` | War Report 单请求超时（秒）。**别写成空值**：空串会让 `Settings()` 在导入期报错、进程起不来（compose 的 `${VAR:-默认}` 会把空值换回默认，直接跑 uvicorn 则没有这层保护） |

```bash
git check-ignore .env && echo OK   # 必须有输出：.env 绝不能入库
```

### 端口由 `PUBLIC_BASE_URL` 决定（改端口的唯一入口）

**对外端口是 `PUBLIC_BASE_URL` 的一部分**：`http://1.2.3.4:7788` → 对外 7788；
没写端口就是 `http`→80 / `https`→443。想换端口**只改 `.env` 这一行**，别去动
compose —— 端口与媒体绝对 URL 必须始终一致，改岔了投稿图片全裂。

docker compose **只会做整值 `${VAR}` 插值、没有子串运算**，没法在 YAML 里从 URL 里
抠出端口，所以这一步由 `deploy/compose.sh` 完成：读 `.env` 的 `PUBLIC_BASE_URL`
→ 解析端口 → 导出 `WEB_PORT` → 转交 `docker compose`。

**因此：请用脚本启动，不要直接 `docker compose up -d`。**

```bash
./deploy/compose.sh up -d            # 首次 / 日常启动
./deploy/compose.sh up -d --build    # 改了代码要重建镜像
./deploy/compose.sh logs -f web
./deploy/compose.sh ps

./deploy/compose.sh --print-port     # 只打印推导出的端口，不碰 docker（排障用）
```

脚本是 `docker compose` 的**薄包装**：其余参数原样透传，行为一致。

> 直接跑 `docker compose up -d` 不会报错，但会**回落到 80 端口**
> （compose 里写的是 `${WEB_PORT:-80}:80`）。于是站点跑在 80 上，而
> `PUBLIC_BASE_URL` 写的是 7788 —— 浏览器能打开页面，但投稿图片的绝对 URL
> 指向 7788，全裂，且没有任何报错。**这就是为什么这层包装值得存在。**
>
> 万一你就是想手动调 compose，先导出端口再执行：
> `export WEB_PORT=$(./deploy/compose.sh --print-port) && docker compose up -d`

**改端口后还要放行防火墙与云安全组**（两道都得做，见 §1 前置条件）：

```bash
# Ubuntu/Debian
ufw allow 7788/tcp && ufw status
# CentOS/RHEL
firewall-cmd --permanent --add-port=7788/tcp && firewall-cmd --reload
```

云厂商安全组（阿里云/腾讯云/华为云控制台）也要另加一条入方向规则
`TCP:7788` —— **这一步漏了的话，服务器上 `curl localhost:7788` 正常，
外网就是打不开。**
```

### 陷阱：密码里的 `$` 会被 compose 插值

**`.env` 的值也会被 compose 做变量插值**，而且**静默截断**——不报错，只留一条 warning。

实测（2026-10-20，compose v2 本机验证）：

| `.env` 里写的值 | compose 实际给容器的值 | 警告 |
| --- | --- | --- |
| `PW=:jL$i6JEk*^!`（无引号） | `:jL*^!` ← `$i6JEk` 被当变量、没设 → 变空串 | 有 |
| `PW=":jL$i6JEk*^!"`（双引号） | `:jL*^!`（同上，双引号**也**插值） | 有 |
| `PW=':jL$i6JEk*^!'`（单引号） | 原样保留（单引号 = 不插值） | 无 |

**所以密码只用字母数字**（`$ : @ # / %` 一律避开）。`$` 尤其危险：它既会被插值，
还会进 `DATABASE_URL`（compose 第 45 行把密码拼进 URL），两处一起被改。
需要特殊字符时用**单引号**包住整个值。

插值截断是**两边同步**的（`POSTGRES_PASSWORD` 与 `DATABASE_URL` 读同一个值），
所以认证仍能对上——但你以为设的密码已经不是那个了。**改密码后要同步改数据库里的角色**：

```bash
docker compose exec postgres psql -U coc -d coc -c "ALTER USER coc WITH PASSWORD '新密码';"
```

### 陷阱：改 `.env` 里的密码 ≠ 改了数据库的密码

**postgres 角色的密码在数据卷第一次初始化时就被冻结了。** 官方镜像只对**空**数据目录
应用 `POSTGRES_PASSWORD`；之后无论怎么改 `.env`，数据库里的角色密码都不会变。
于是 api 连不上：

```
asyncpg.exceptions.InvalidPasswordError: password authentication failed for user "coc"
```

而且 api 容器会变成 **`unhealthy`**（探针 `/readyz` 连不上 DB —— 这正是用 `/readyz`
而不是 `/healthz` 的价值）。

**改密码必须两边一起改**（容器内本地连接是 `trust`，不需要旧密码）：

```bash
NEW=$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24)
docker compose exec postgres psql -U coc -d coc -c "ALTER USER coc WITH PASSWORD '$NEW';"
# 把 .env 里的 POSTGRES_PASSWORD 改成同一个 $NEW（纯字母数字，别带 $ 等会被插值的字符）
docker compose up -d          # 改 .env 必须 up -d 重建，restart 不重读环境变量
docker compose ps             # api 应回到 healthy
```

**不确定当前生效密码时，用确定式的做法**（别猜「我以为的值」——`.env` 里的字面量
不等于 compose 插值后的值）：

```bash
# 1) 读出 compose 实际给容器的值
PW=$(docker compose exec -T postgres printenv POSTGRES_PASSWORD | tr -d '\r')
echo "生效密码: [$PW]"
# 2) 把库里的角色密码对齐成这个值（本地 trust，不需要旧密码）
docker compose exec -T postgres psql -U coc -d coc -c "ALTER USER coc WITH PASSWORD '$PW';"
# 3) 清掉连接池里的旧连接
docker compose restart api
curl -s http://127.0.0.1/readyz      # {"status":"ready"}
```

> 步骤 1 的值里若含单引号，步骤 2 的 SQL 要相应转义；含 `$` 的话说明 `.env` 还没改干净
> （`$xxx` 会被 compose 当变量插值），先按上面「密码里的 `$` 会被 compose 插值」处理。

> 排查时先确认「两边」现在各是什么：`docker compose exec postgres printenv POSTGRES_PASSWORD`
> 与 `docker compose exec api printenv DATABASE_URL` —— 它们一定一致（同一个 `.env`），
> 不一致的是**库里的角色密码**（读不出来，只有哈希），所以直接 `ALTER USER` 统一最省事。

## 3. 启动与建表

```bash
./deploy/compose.sh up -d --build   # 首次较久：前端要 npm ci + vue-tsc
docker compose ps
```

> **构建耗时**：api 镜像要装全部 Python 依赖，**第一次**构建要下全量
> （实测十几到二十分钟，取决于到 PyPI 的带宽）。之后：
>
> - **只改代码** → 只重建「装应用自身」那一层，依赖层全部命中缓存，实测十几秒；
> - **改了 `pyproject.toml` 的依赖** → 依赖层失效，回到"装依赖"的时间（下载仍走缓存）。
>
> 做法是把依赖安装与源码拷贝拆成两层：依赖清单从 `pyproject.toml` 抽出来单独装
> （`pip install -r /tmp/requirements.txt`），应用自身用 `pip install --no-deps .`
> 单独装。**别把 `COPY app` 挪回依赖安装之前** —— 那样改一行代码就会重装全量依赖，
> 有测试守着这条（`backend/tests/test_deployment_config.py`）。
>
> Dockerfile 用 BuildKit cache mount（`--mount=type=cache,target=/root/.cache/pip`）
> 缓存 pip 的下载，缓存**不进镜像层**。
> 需要 BuildKit（Docker 23+ 默认启用）；若报 `--mount option requires BuildKit`，
> 用 `DOCKER_BUILDKIT=1` 或升级 Docker。

期望状态【首跑核对】：

| 服务 | 期望 |
| --- | --- |
| postgres | `running (healthy)`（healthcheck = pg_isready） |
| api | `running (healthy)`（healthcheck = 容器内 curl `/readyz`） |
| web | `running` |

> api 的探针是 **`/readyz`**（连 DB 验证）而不是 `/healthz`（进程存活即 200）——
> 用后者的话 DB 挂了容器照样"健康"。

首次启动建表（api 镜像里带了 `alembic.ini` + `migrations/`）：

> **镜像里只有 `pyproject.toml` 声明过的依赖。** 本机环境多出来的包（孤儿包）不会进镜像，
> 于是「本机测试全绿、容器启动即崩」——这是真实发生过的坑（`itsdangerous`）。
> `backend/tests/test_runtime_deps.py` 守着这条：它把孤儿包屏蔽掉再 import 一次应用，
> 复现镜像环境。**加了新依赖记得进 `dependencies`。**

```bash
docker compose exec api alembic upgrade head    # 跑完 10 个迁移
docker compose exec api alembic current         # 期望： a7f3c1d90e42 (head)
```

表数量核对【已验证·本机同一迁移链，2026-10-19 实测】：

```bash
docker compose exec postgres psql -U coc -d coc -c \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"
# 期望 28 = 27 张业务表 + alembic_version
```

## 4. 导入升级数据

数据源是 MIT 协议的开源 npm 包 `clashofclans.js@4.0.5`（**与 Supercell API 无关，
不占配额**），upsert 幂等、可重复执行。容器需要能访问 `registry.npmjs.org`：

```bash
docker compose exec api python -m app.cli import-game-data
```

期望输出【已验证·本机同代码实测，2026-10-19】：

```
写完 2073 行{'troop': 599, 'spell': 111, 'hero': 513, 'equipment': 850}
```

核对 SQL（本机 psql 实测通过，可原样复制）：

```bash
docker compose exec postgres psql -U coc -d coc -c \
  "SELECT category, count(*) FROM upgrade_items GROUP BY category ORDER BY count DESC;"
# equipment |   850
# troop     |   599
# hero      |   513
# spell     |   111
```

不导入的话，升级相关接口全部返回空列表，`/admin/` 的「升级条目」也是空的。
`name_zh` 导入阶段刻意留空（不猜翻译），要人工在后台补。

## 5.（无 Token 时的）夹具数据与排行榜

`COC_API_TOKEN` 为空（或字面量 `PLACEHOLDER`，大小写不敏感）时，后端不打官方 API，
由 `app/coc/devfixtures.py` 的 FixtureTransport 用 `backend/app/coc/fixtures/` 的本地样本
应答：**HTTP 契约完全真实，数据是手搓占位**（响应自带 `_source`/`_todo` 键自报身份），
玩家详情永远返回同一个样本玩家——不是 bug，接 Token 后消失。

> ⚠️ **只有「空」或「PLACEHOLDER」才算占位。** 填了别的任何值（比如 `your_token_here`），
> 后端就**走真实上游**了 —— 这时用夹具里的假 tag（`#9QJ8L0` / `#2PP`）查询会得到
> `404 PLAYER_NOT_FOUND`，那是**正确行为**（官方上确实没有这两个 tag）。
> 另外注意：`/api/v1/locations` 读的是**数据库**（`locations` 表 + `is_country` 过滤），
> 不走上游 —— 所以它返回夹具数据**不能**证明后端还在夹具模式。

让排行榜页有东西可看：

```bash
docker compose exec api python -m app.cli seed-dev-rankings
# 期望： 已灌入： {'locations': 4, 'rankings': 3}
# 幂等（走全量替换），重复跑不会翻倍【已验证·本机重复执行】
```

## 6. 接入真实 Supercell Token

1. Supercell 开发者后台建 API key。
2. **服务器无静态 IP**（最常见）→ `.env` 两行：

   ```bash
   COC_API_TOKEN=你的token
   COC_BASE_URL=https://cocproxy.royaleapi.dev/v1
   ```

   并且 key 的 **Allowed IP 填 `45.79.218.79`（RoyaleAPI 代理的 IP）**，
   **不要**填服务器 IP。代理只换域名转发，路径/鉴权/错误语义全不变。
3. 服务器有静态 IP → 清空 `COC_BASE_URL`，Allowed IP 填服务器 IP。
4. 生效方式（改了 `.env` 必须重建容器）：

   ```bash
   ./deploy/compose.sh up -d
   ```

5. 验证切换成功（**必须用真实存在的 tag**，夹具里的 `#9QJ8L0` 在官方上不存在）：

   ```bash
   curl -s "http://127.0.0.1/api/v1/clans/%23你的真实部落TAG" | head -c 300
   ```

   怎么读结果：

   | 响应 | 含义 |
   | --- | --- |
   | 200 + JSON | ✅ 上游通了（Token 有效、白名单 OK），只是之前那个 tag 是假的 |
   | 403 `accessDenied` | 白名单/Token 问题，见下方诊断表 |
   | 404 `PLAYER_NOT_FOUND` | 上游通了，但这个 tag 不存在（**正常**，用真 tag 再试） |

   **403 诊断**：

   | 接入方式 | Supercell key 的 Allowed IP 填 |
   | --- | --- |
   | 走代理（`COC_BASE_URL=https://cocproxy.royaleapi.dev/v1`） | **代理的 `45.79.218.79`**（不是服务器 IP） |
   | 直连官方（`COC_BASE_URL` 留空） | 服务器**公网 IP**（`curl -s ifconfig.me`） |

6. **切到真实 Token 后，清掉夹具种子留下的假排行**：

   ```bash
   docker compose exec postgres psql -U coc -d coc -c "DELETE FROM rankings;"
   ```

   `seed-dev-rankings` 灌的是**手搓的 3 条假排行**；真实采集按 scope **全量替换**，
   采到的 scope 会被覆盖，但在第一次采集成功之前，假数据会**冒充真榜单**被吐出去。
   `locations` 表不用清 —— 那 4 行用的都是真实官方 id（Global / Bosnia / China /
   International），`static_data` 采集会 upsert 补齐其余地区。

7. 看采集状态（真实模式下排行榜靠 `app/collector/` 定时采集，不在实时查询路径上）：

   ```bash
   curl -s http://127.0.0.1/api/v1/meta/freshness | python3 -m json.tool
   # data.rankings：每地区每类榜单的最后采集时间
   # data.collectorRuns：最近 20 次采集任务（job 可能状态：success/failed/partial）
   # 调度周期【已验证·scheduler.py】：rankings 每 6h（:13 分）、leagues/seasons 每 1h（:41/:29）、static_data 每天（03:17 UTC）、warreport 每天（04:23 UTC），全部错开整点
   ```

> 红线：代理是社区免费共享的，**不要把 `COC_RATE_LIMIT` 调高**；把它当成"救慢采集"
> 的手段 = 把成本转嫁给运维代理的人。

8. **不想等 cron？手动采一次**（详见 §7）：

   ```bash
   docker compose exec api python -m app.cli collect rankings
   ```

   换好 Token 后第一次采集不必干等下一个 cron 点（rankings 最长 6 小时）。

## 7. 日常运维

### 改了 `.env` 之后：必须 `up -d`，不能 `restart`

**`.env` 是给宿主机上的 compose 读的**：compose 解析完再把值**注入**容器环境变量，
`.env` 文件本身**没有**挂进容器（`app/config.py` 的 `env_file=".env"` 在容器里没有文件可读）。
所以：

| 命令 | 新 `.env` 生效吗 | 说明 |
| --- | --- | --- |
| `./deploy/compose.sh up -d` | ✅ | compose 比对解析后的配置，**变了就重建**该容器 |
| `docker compose restart` | ❌ | 只重启进程，**沿用容器创建时的环境变量** |
| `./deploy/compose.sh down && ./deploy/compose.sh up -d` | ✅ | 等价但更慢（`down` 不删卷，除非加 `-v`） |

> `docker compose` 不带脚本时也生效，只是**端口会回落到 80**（见 §2「端口由
> `PUBLIC_BASE_URL` 决定」）。所以**一律用脚本**。

**只有受影响的服务会被重建**：只改 `COC_API_TOKEN` → 只重建 api；改 `POSTGRES_PASSWORD`
→ postgres 与 api 都要重建（`DATABASE_URL` 是 compose 拼出来的，跟着变）。

改完验证：

```bash
docker compose ps                                # 看 CREATED 时间变了没有
docker compose exec api printenv COC_API_TOKEN  # 看容器里真实拿到的值
```

> `docker compose config` 也能看解析后的值，但它会把**密钥明文**打出来 ——
> 别把它的输出贴进聊天或工单。

### 改配置 ≠ 改环境变量

| 改了什么 | 要做什么 |
| --- | --- |
| `.env` 里的变量 | `./deploy/compose.sh up -d`（重建容器） |
| `deploy/nginx.conf` | `docker compose exec web nginx -s reload`（bind mount，改完即生效，**不用重建**） |
| 后端代码 | `docker compose build api && ./deploy/compose.sh up -d` |
| 前端代码 | `docker compose build web && ./deploy/compose.sh up -d` |
| 数据库结构 | `docker compose exec api alembic upgrade head` |

### 日志与状态

```bash
docker compose ps                       # 三个服务的状态
docker compose logs -f api              # 应用日志（**服务名是 api，不是 nginx**）
docker compose logs -f web              # nginx 访问日志
docker compose logs --tail=100 api      # 最近 100 行
```

### 手动触发一次采集

调度器按 cron 触发（`rankings` 每 6 小时、`leagues`/`seasons` 每小时、`static_data` 每天、
`warreport` 每天 04:23 UTC）。刚换好真实 Token 时不必干等：

```bash
docker compose exec api python -m app.cli collect rankings     # 也可 static_data / leagues / seasons / warreport
docker compose exec api python -m app.cli collect --help
```

它走的是**和调度器完全同一条路径**（`app.collector.service.run_job`）：同样的运行留痕、
同样的部分失败记账、同样的令牌桶。输出 `采集 job rankings -> success` 即完成；
`partial` 表示部分地区失败（明细看 `collector_runs.error`）。

各 job 的「正常长相」（2026-10-21 真实 Token 实测，拿来对照）：

- `leagues` → `success (ok=88 failed=0)`（联赛、都城联赛、建筑大师联赛、联赛层级合并计数）。
- `seasons` → `success (ok=6 failed=0)`：赛季清单翻到底（3 次请求）后**只留最近 6 个**，
  并抓当前赛季的 200 名。核对 `SELECT count(*) FROM seasons WHERE league_id=29000022;` = 6。
- `rankings` → 常见 `partial`：1275 个 scope 里偶尔 1–2 个上游 `525`（代理到源站的 TLS
  握手失败）。**这不是 bug**，下一轮会自愈；只有大面积 `failed` 才需要查 Token / 白名单。

### 备份与恢复

脚本：`backend/deploy/backup.sh`（数据库全量 + 媒体目录 + 自动清理 14 天前的旧备份）。
它已适配本仓库：**自动 cd 到仓库根**再执行 `docker compose`；媒体卷名默认
`cocpersonal_media`（compose 项目名是 cocpersonal），可用 `MEDIA_VOLUME` 覆盖。

```bash
# 手动跑一次（任意目录都行）
/opt/cocpersonal/COCPersonal/backend/deploy/backup.sh

# crontab（错开整点，避免与上游/任务高峰撞在一起）
crontab -e
# 17 4 * * * /opt/cocpersonal/COCPersonal/backend/deploy/backup.sh >> /var/log/coc-backup.log 2>&1
```

**不清理的话备份会把磁盘吃满**，而磁盘满的直接后果是**数据库写不进去** ——
现象是「服务看着正常但数据不再更新」，比没有备份更难排查（脚本默认保留 14 天）。

恢复（`pg_dump --clean --if-exists` 是**整库替换**，不是合并）：

```bash
gunzip -c /opt/cocpersonal/COCPersonal/backups/db-2026-10-21.sql.gz | \
  docker compose exec -T postgres psql -U coc -d coc
```

> 恢复前先把当前库再备份一份。恢复是替换式的，别指望与新数据合并。

### 升级发版

```bash
cd /opt/cocpersonal/COCPersonal
git pull
./deploy/compose.sh up -d --build     # 只改 .env/nginx.conf 时不必 --build
docker compose exec api alembic upgrade head
```

- **顺序**：备份 → `git pull` → 重建 → `up -d` → 建表。
- **改了 `.env` 必须 `up -d` 重建**（见本节开头）。
- 迁移出错时对照两个 revision：`alembic current`（库里到哪了）与
  `alembic heads`（代码里最新到哪了）；`alembic heads` 出现**两个** head
  = 有人手写了迁移没接对。

### 限流与缓存观察

对外限流 `RATE_LIMIT_PER_MINUTE=60`（每 IP 每分钟）；`/healthz` 与 `/readyz` 不计桶。
被限流不用重启，等一分钟即恢复；`X-Forwarded-For` 已透传，所以按真实客户端 IP 计数。

缓存状态看响应里的 `meta.cache`（`HIT` / `MISS` / `STALE`），TTL 看 `meta.ttl_seconds`
（详情类：部落/玩家 300s、战报 120s）。

## 8. 冒烟验证（假设服务器 IP 是 `1.2.3.4`）

| # | 操作 | 期望 |
| --- | --- | --- |
| 1 | `curl -s http://1.2.3.4/healthz` | `{"status":"ok"}` |
| 2 | `curl -s http://1.2.3.4/readyz` | `{"status":"ready"}` |
| 3 | 浏览器 `http://1.2.3.4/` | 首页正常渲染（侧边栏「查询 / 排行榜」） |
| 4 | 首页输入 `8qu8j9j` 回车 | 跳 `/players/%238QU8J9J` 并渲染（夹具模式始终显示同一占位玩家） |
| 5 | 排行榜 tab | 按地区/联赛切换可见数据（夹具数据，需已跑 §5） |
| 6 | `curl -s http://1.2.3.4/api/v1/players/%239QJ8L0` 连发两次，看 `meta.cache` | 第一次 `MISS`，第二次 `HIT`【已验证·本机】 |
| 7 | 手改 URL `http://1.2.3.4/no-such-page` | 友好 404 页（不是白屏） |
| 8 | `http://1.2.3.4/admin/` | 登录页可用 `ADMIN_USERNAME`/`ADMIN_PASSWORD` 登入 |
| 9 | `curl -sI http://1.2.3.4/media/` | 403（`autoindex off` 生效）；出现**目录列表** = 配置被改坏 |
| 10 | 后台「升级条目」 | 有 2073 条数据（§4 已导入则 `name_zh` 为空待补） |

> 浏览器冒烟八项的完整清单（导航、查询跳转、错误输入不跳转、404 页、二次加载 HIT）
> 在本机 Vue+uvicorn 组合下已逐项实测通过（2026-10-17，记录于
> `docs/superpowers/plans/2026-10-16-cocpersonal-mvp.md`）；容器环境下按上表复核。

## 9. HTTPS 升级（可选，默认 HTTP-only）

默认单端口 80（`deploy/nginx.conf` 末尾有 HTTPS 注释块）。需要域名（§1 可选项）：

1. **compose**（`docker-compose.yml` 的 web 服务加两个挂载）：

   ```yaml
   volumes:
     - ./deploy/nginx.conf:/etc/nginx/conf.d/default.conf:ro
     - media:/data/media:ro
     - ./deploy/certs:/etc/nginx/certs:ro          # 新增：证书
     - ./deploy/certbot-www:/var/www/certbot       # 新增：ACME 验证目录
   ```

   > **不用加端口行**：`deploy/compose.sh` 看到 `PUBLIC_BASE_URL` 是 `https://`
   > 就自动把**宿主机侧**端口取 443、**容器侧**端口取 443（容器内 nginx 的 TLS
   > server 块）。两侧必须一致 —— 把 https 流量转到容器的 80 端口，nginx 会用
   > **明文**应答，浏览器直接报 TLS 握手失败，而容器日志里看不出任何异常。
   >
   > 想用非标准端口（如 `https://coc.example.com:8443`）就写进 `PUBLIC_BASE_URL`，
   > 脚本会据此推导：宿主机 8443 → 容器 443。

2. **nginx.conf**：80 端口 server 里加一段（放最前，否则会被 301 拦掉）：

   ```nginx
   location ^~ /.well-known/acme-challenge/ {
       root /var/www/certbot;
   }
   ```

   再按文件末尾注释块：取消 443 ssl server 注释，把 80 server 的所有业务 location
   原样**复制**进 443 server（nginx 不允许跨 server 复用 location）；80 的 location /
   改为 `return 301 https://$host$request_uri;`。
3. **签证书**（宿主机 certbot，webroot 模式写到挂载进容器的目录）：

   ```bash
   mkdir -p /opt/cocpersonal/deploy/certs /opt/cocpersonal/deploy/certbot-www
   sudo certbot certonly --webroot -w /opt/cocpersonal/deploy/certbot-www \
        -d coc.example.com --email you@example.com --agree-tos --no-eff-email
   sudo cp "/etc/letsencrypt/live/coc.example.com/fullchain.pem" /opt/cocpersonal/deploy/certs/
   sudo cp "/etc/letsencrypt/live/coc.example.com/privkey.pem"  /opt/cocpersonal/deploy/certs/
   ```
4. **生效**（nginx.conf 是 bind mount，reload 即可；首次开 443 端口要 `up -d`）：

   ```bash
   ./deploy/compose.sh up -d
   docker compose exec web nginx -s reload
   ```

   `PUBLIC_BASE_URL` 改成 `https://coc.example.com` 后再 `./deploy/compose.sh up -d`
   （改的是 `.env`，必须重建容器，不能只 reload）。注意这一步会把对外端口切到
   **443**（`https` 的默认端口）—— 若你想保留 80/7788 之类的自定义端口，
   `PUBLIC_BASE_URL` 里要显式写出来：`https://coc.example.com:443` 或
   `https://coc.example.com:7788`。
5. **自动续期**：遗留的 `backend/deploy/certbot-renew.sh` 引用 compose 里不存在的
   `certbot`/`nginx` 服务，**只能当思路参考**。本仓库等价做法（宿主机 crontab）：

   ```cron
   17 3,15 * * * certbot renew --quiet --webroot -w /opt/cocpersonal/deploy/certbot-www \
     --deploy-hook "cp -f /etc/letsencrypt/live/coc.example.com/*.pem /opt/cocpersonal/deploy/certs/ && docker compose -f /opt/cocpersonal/docker-compose.yml exec -T web nginx -s reload"
   ```

   更稳的写法是把 hook 存成脚本（先 `nginx -t` 合法性检查再 reload），思路照抄
   `certbot-renew.sh` 的注释。
6. **验证**：`curl -I https://coc.example.com/healthz` 期望 200；
   `curl -sI http://域名/` 期望 301；浏览器锁图标 / `/media/` 图片正拼成 https。

> 以上 HTTPS 流程**从未在任何机器真实执行过**（compose 无 certbot 服务是刻意简化），
> 启用时按【首跑核对】心态逐条验证。小程序风格的"先 HTTP 起服务再签证书"顺序
> 完全适用：80 端口先跑起来，webroot 才写得进验证文件。

## 10. 首跑验收清单（compose 从未在本机真实 up 过）

> **首次真实 `up` 已于 2026-10-20 在 Linux 服务器上跑通**，第 1–5 项已逐条核对通过
> （两个镜像构建完成、三容器 healthy、`alembic current` = `d4c8a36b19e6 (head)`、
> 表数 28）。**第 6–12 项（导入数据与冒烟）当时尚未执行。**
> 该 head 之后已推进（当前 `a7f3c1d90e42`，迁移 0010 放宽赛季 id 列宽），表数不变。
> 首跑还暴露了「镜像缺 `itsdangerous`」的缺陷，已修（账本 Task 14）——这正是本清单存在的意义：
> 文档写对了不等于栈跑得起来。

第一次真实部署时**逐条打勾**，任何一步与期望不符：停下来记录偏差、修正本文档，
再继续下一步 —— 这份文档的价值取决于它被"实测"的程度。

| # | 步骤 | 命令 | 期望 |
| --- | --- | --- | --- |
| 1 | compose 校验 | `docker compose config --quiet` | exit 0，无输出 |
| 2 | 镜像构建 | `docker compose build` | 两个本地镜像构建成功 |
| 3 | 容器健康 | `docker compose ps` | §3 表格状态 |
| 4 | 迁移 | `docker compose exec api alembic current` | `a7f3c1d90e42 (head)`【已验证·本机同迁移链】 |
| 5 | 表数 | information_schema 计数 | 28（§3）【已验证·本机】 |
| 6 | 升级数据 | 2073 行按四类分布 | §4【已验证·本机】 |
| 7 | 探针 | `/healthz` `/readyz` | §8 第 1/2 行 |
| 8 | 前端 | `curl -sI http://127.0.0.1/` | 200, `text/html` |
| 9 | 缓存 | `meta.cache` MISS→HIT | §8 第 6 行 |
| 10 | 后台 | SQLAdmin 登录 | §8 第 8 行 |
| 11 | 镜像依赖 | `docker compose exec api python -c "import itsdangerous"` | 无报错（镜像里只有声明过的依赖，见 §3 提醒） |
| 12 | `.env` 插值 | `docker compose config 2>&1 \| grep "not set"` | **无输出**——有输出说明某个值里的 `$xxx` 被静默截断了（§2 陷阱） |
| 13 | **端口一致** | `./deploy/compose.sh --print-port` 与 `docker compose ps` 里 web 的映射 | 两边端口相同（见 §2「端口由 PUBLIC_BASE_URL 决定」） |

## 11. 常见故障速查

| 症状 | 检查点 |
| --- | --- |
| api 反复重启（`Restarting (1)`） | 这是 **uvicorn 导入期失败**（exit 1），不是运行期错误：`docker compose logs api --tail 50` 看 traceback。两种常见根因：① 镜像缺依赖（`ModuleNotFoundError`）——依赖声明在 `pyproject.toml`，`backend/tests/test_runtime_deps.py` 守着这条；② 代码版本过旧（`AttributeError: module 'app.main' has no attribute 'app'`）→ `git pull` 后重建 |
| 每次重建 api 都要等十几分钟 | pip 缓存没生效：确认 Dockerfile 里**没有** `PIP_NO_CACHE_DIR=1`，且 `RUN` 带 `--mount=type=cache,target=/root/.cache/pip`；另外要 BuildKit（`DOCKER_BUILDKIT=1` 可强制开启） |
| `up` 直接报 `POSTGRES_PASSWORD 必填` | `.env` 没建、不在仓库根、变量名拼错（compose 的 `${VAR:?}` 在拦你，好事） |
| api 反复重启，日志 `connection ... postgres refused` | postgres 还没 healthy，等 start_period（40s）过完再看；仍不行查 `POSTGRES_PASSWORD` 是否两边一致 |
| 页面 502 | `docker compose logs -f api`；`readyz` 手动 curl 试 |
| api 起不来，日志见 `sqlalchemy ... version mismatch` | 别动 `pyproject.toml` 里 `sqlalchemy<2.1` 的上盖——2.1.x 的 wheel 有真实问题（本机逐字节比对验证过），锁版本不是保守是教训 |
| 刷新详情页变 404 | SPA fallback：`location /` 里的 `try_files ... /index.html`；检查是否改坏了 `deploy/nginx.conf` |
| 后台登录失败 | `.env` 的 `ADMIN_USERNAME`/`ADMIN_PASSWORD` 大小写、多余引号；改后**必须** `docker compose up -d`（凭据只进环境变量） |
| 头像/媒体图片裂 | `PUBLIC_BASE_URL` 协议或地址不对（拼的是绝对 URL） |
| **浏览器能开页面，但投稿图片全裂** | 端口两边不一致：多半是直接跑了 `docker compose up -d`（回落到 80）而 `PUBLIC_BASE_URL` 写的是别的端口。查 `./deploy/compose.sh --print-port` 与 `docker compose ps` 里 web 的映射，两边应一致 |
| **改了 `.env` 的端口，站点还在老端口上** | `docker compose restart` **不重读**环境变量，必须 `./deploy/compose.sh up -d`（重建容器才会换端口绑定） |
| **外网打不开、服务器上 `curl localhost:端口` 正常** | 防火墙/云安全组没放行那个端口。两道都要查：系统防火墙（`ufw`/`firewall-cmd`）与云厂商控制台的安全组入方向规则 |
| https 站点报 TLS 握手失败 | 容器内没有 443 server 块（或 `deploy/nginx.conf` 里 443 段还注释着）——把 https 流量转到容器的 80 端口，nginx 会用明文应答。见 §9 |
| **api `unhealthy` + 日志 `password authentication failed for user "coc"`** | `.env` 的密码改了，但**库里的角色密码在数据卷初始化时就冻结了** → 必须 `ALTER USER` 同步（见 §2 陷阱） |
| 大量 429 | 真实客户端超 60 次/分；`X-Forwarded-For` 已透传，问题多半在共享出口 IP；临时下调 `RATE_LIMIT_PER_MINUTE` 需重启 api |
| 排行榜空 | 夹具模式没跑 §5；真实模式 `meta/freshness` 看采集时间和 `collectorRuns`，补采命令见 §12.3 |
| 磁盘满 | `backup.sh` 未设时备份会吃满磁盘——恢复它或手动清理（磁盘满的表象是"服务正常但数据不再更新"） |

## 12. War Report 数据源与署名

赛季榜与阵容页的数据来自第三方 **[War Report](https://warreport.app)**（只读 API
`https://api.warreport.app`）。它与 Supercell 官方链路**完全独立**：不需要 API Key、
没有 IP 白名单、不占令牌桶，默认配置就能跑。「阵型」页本期只是占位，没有数据源。

### 12.1 端点与调度

| 用途 | 上游端点 | 落库 |
| --- | --- | --- |
| 赛季玩家榜 | `GET /locations/global/rankings/players?season=YYYY-MM-DD` | `rankings`（kind=`wr_season_players`） |
| 赛季部落榜 | `GET /locations/global/rankings/clans?season=YYYY-MM-DD` | `rankings`（kind=`wr_season_clans`） |
| 热门配兵（阵容页） | `GET /armies` | `warreport_armies`（每次整表替换） |
| 快照探测 | `GET /locations/global/rankings/players/countries?season=...` | 不落库（3.8 KB） |

- 采集 job 名 `warreport`，**每天 `04:23 UTC` 一次**（cron `23 4 * * *`，错开整点）。
  上游快照 28 天才出一份，每天一次已经足够。
- **启动时会自动补一次**（`app/collector/catchup.py`，挂在 `register_jobs` 的
  `startup_catchup` 一次性任务上）：某个 job 最近一次运行超过自己的周期，或最近一次
  不是 `success`（含卡在 `running` 的崩溃残留），就补跑一轮；失败后 5 分钟内不重复补，
  避免崩溃重启连环打上游。
  **这台服务器不是 7×24 在线时必须有这层**：cron 会在关机时段静默错过 —— 尤其
  `warreport` 的 04:23 UTC（北京 12:23），错过一次就等第二天，页面表现为「一直空」
  而调度器和接口全都正常。
- 调度器与 API **同进程**：`APP_ROLE=all`（默认）或 `collector` 才会跑；`api` 角色不跑
  调度器（多起一个只是白跑）。角色门控见 `backend/app/collector/scheduler.py`。
- 对外路由（`/api/v1/rankings/warreport/...`、`/api/v1/armies`）**只读库、绝不回源**，
  所以没有 STALE 降级路径；数据新不新看响应里的 `meta.fetched_at`。

### 12.2 首次运行会多打一些请求（正常）

上游**没有**赛季列表接口，响应里也不带日期，所以「某个赛季是否存在」只能拿
`players/countries?season=YYYY-MM-DD` 逐个试：

- 库里已有快照：只探「最新已知 + 28 天」那一档的最多 3 个候选日期（若最新已知已过
  31 天仍探不到新快照，会判定锚点不可信、回退到逐日回溯）；
- 全新部署（库里没有快照）：从今天往前逐日回溯（最多 35 次），命中后按 28 天间隔
  补探，一次凑满最近 3 个赛季 —— 2026-10-23 首跑实测是 **19 次逐日探测 + 最多 6 次
  补探**；
- 回 `404 {"error":"snapshot not found"}` = **这个日期没有快照，是正常结果**，不计失败；
  只有网络错误/5xx 才计失败（否则「快照永远不更新」会被记成 success）。

所以首跑比之后吵一些是设计使然，第二次运行起只探 3 个候选。上游是共享公共服务，
**不要**为了「快点看到数据」把它改成高频轮询。

### 12.3 验证

```bash
# 空库先灌维表：rankings 只采 locations 里已有的地区（全服 32000000），
# 维表为空时 rankings 会以 success 收场却一行都不写。
docker compose exec api python -m app.cli collect static_data

# 实时榜（官方 API；需要有效 Token，走代理时还要把代理 IP 加进 Allowed IP）
docker compose exec api python -m app.cli collect rankings

# 赛季榜 + 阵容（第三方 War Report，无需 Token）
docker compose exec api python -m app.cli collect warreport
# 期望：采集 job warreport -> success (ok=7 failed=0)
# ok 数的是**成功的 scope**（3 个快照 × 玩家/部落两类榜 + 阵容 = 7），不是行数。
# 首次部署若只探到 1 个快照，ok 会相应少几个 —— 看 items_failed 是否为 0 更可靠。

# 接口侧（路由只读库，采完就能看到）
curl -s http://127.0.0.1/api/v1/rankings/warreport/seasons | python3 -m json.tool
curl -s "http://127.0.0.1/api/v1/rankings/warreport/seasons/2026-10-05/players?page_size=5"
curl -s http://127.0.0.1/api/v1/armies | head -c 300
```

赛季列表最多 3 条（`2026-10-05` / `2026-09-07` / `2026-08-10`，具体以当日上游为准）；
阵容条数**不要写死**：返回的是「当前快照里出现过的配兵」，实测会变。

### 12.4 上游不可用时

- 采集 job 记 `failed`/`partial`，明细进 `collector_runs.error`；看最近 20 次运行
  `curl -s http://127.0.0.1/api/v1/meta/freshness` 的 `data.collectorRuns`。
- **旧数据继续可读**：路由不触上游，所以赛季榜与阵容页**不会 500**，最多停在上一轮。
- 探测阶段的网络错误会让**整轮**记失败，不会被伪装成「今天没有新快照」——
  这是刻意的：否则赛季榜永远不更新也看不出来。

### 12.5 署名（使用条件，不是装饰）

上游 OpenAPI 原文：*Attribution required: Applications using this API must credit
War Report.* 本站落点三处，**改页面时不得移除**：

| 位置 | 文案 |
| --- | --- |
| 排行榜「赛季榜」面板底部 | 数据来源：War Report · 非 Supercell 官方，未获 Supercell 背书 |
| 阵容页底部 | 同上 |
| 全站页脚 | 本站为非官方粉丝站点 · 数据来源：Supercell 官方 API、War Report |

- 组件 `frontend/src/components/SourceNote.vue`（赛季榜与阵容页共用），页脚在
  `frontend/src/layouts/MainLayout.vue`。
- 两处文案与链接都由前端测试盯着（`SourceNote.spec.ts`、`Rankings.spec.ts`、
  `Armies.spec.ts`、`MainLayout.spec.ts`），删掉会红。
- 链接：https://warreport.app

### 12.6 非官方声明

War Report 的数据本身是**非官方**的（上游 OpenAPI：*This material is unofficial and is
not endorsed by Supercell.*）。本站同样不是 Supercell 官方站点、未获 Supercell 背书；
使用这些数据须遵守 Supercell 的 **Fan Content Policy**
（https://supercell.com/en/fan-content-policy/）。**不要**把赛季榜/阵容说成官方数据，
也不要用于商业售卖。

### 12.7 配置项

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `WARREPORT_BASE_URL` | `https://api.warreport.app` | 上游地址；指向测试假上游时改这里 |
| `WARREPORT_TIMEOUT` | `15`（秒） | 单请求超时 |

两份 `docker-compose.yml` 的 `api.environment` 都已透传这两项（**不是密钥**，所以
`.env.example` 里给的是可用默认值而不是空占位）。改了 `.env` 照例要
`./deploy/compose.sh up -d`，`restart` 不重读环境变量（见 §7）。

## 13. 已知限制

| # | 内容 |
| --- | --- |
| 1 | `docker compose up` 在本机从未真实执行（无 Docker）；§10 清单必做 |
| 2 | 夹具样本是占位数据（`_source`/`_todo` 自报），拿真实 Token 后替换 |
| 3 | `sqlalchemy` 锁 `<2.1`：升依赖时别放宽（见 §11） |
| 4 | 单 worker/单副本：扩展前提是把限流、缓存、调度换成共享实现 + `APP_ROLE` 拆分 |
| 5 | HTTPS 流程从未真实执行（§9） |

## 14. 素材图（Fankit 图标，不进镜像）

`scripts/fetch_fankit_assets.py` 把《部落冲突》图标下到仓库根的 `pictures/`，共
**129 个文件 / 约 175 MB**，按 `army` / `equipment` / `hero` / `pet` / `spell` /
`workshop` 分类，文件名是国服译名。

**这个目录在 `.gitignore` 里**（`.gitignore` 的 `pictures/` 会匹配任意层级，所以
`frontend/public/pictures/` 同样被忽略）—— 它**不在版本库里，也不在镜像里**。
线上要让 `/pictures/...` 能访问，必须满足两个条件：

1. 宿主机的 `frontend/public/pictures/` 存在且有图（`find ... -type f | wc -l` 应为 129）
2. `docker-compose.yml` 里 `web.volumes` 的那行只读挂载在：

   ```yaml
   - ./frontend/public/pictures:/usr/share/nginx/html/pictures:ro
   ```

   `frontend/.dockerignore` 刻意排除 `public/pictures`，避免 175 MB 灌进构建上下文。

改完执行 `./deploy/compose.sh up -d web`（**卷变更必须重建容器**，`nginx -s reload` 不够）。

### 验证：必须看 Content-Type

`deploy/nginx.conf` 的 `location /` 是 `try_files $uri $uri/ /index.html` ——
**任何不存在的路径都会返回 200 + `text/html`**（首页壳）。所以：

```bash
PORT=$(./deploy/compose.sh --print-port)
f=$(ls frontend/public/pictures/army | head -1)
curl -s -o /dev/null -w '%{http_code} %{content_type} %{size_download}\n' \
  "http://127.0.0.1:${PORT}/pictures/army/${f}"
# 期望：200 image/png 7xxxx      ← 这才算通
# 故障：200 text/html 4xxx       ← 挂载没生效，回落到 index.html
```

| 现象 | 原因 |
| --- | --- |
| `200 text/html` | 挂载没生效（没 `up -d web`，或路径写错） |
| `403` | 宿主目录权限：容器内 nginx 是 uid 101，`chmod -R a+rX` |
| 换图后还是旧图 | 浏览器缓存 7d；文件名不带哈希，所以没给 `immutable` |

> `git clean -fdx` 会删掉这批图（被忽略的未跟踪文件），重建要重跑下载脚本。
