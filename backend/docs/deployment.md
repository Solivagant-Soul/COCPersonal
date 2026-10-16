# 部署上线清单

按顺序做完这八步。每一步都有**可复制的命令**和"怎么确认它成功了"。

> **最容易被跳过、且最难排查的一步是第 8 步。** 漏了它，服务器上一切正常、
> 域名也能访问，但小程序端**完全调不通**，报错只说"不在合法域名列表里"，
> 排查方向很容易跑偏到代码和网络上。

---

## 0. 前置条件

| 项 | 要求 |
| --- | --- |
| 服务器 | Linux，2 核 4G 起（单副本一体，资源主要给 PostgreSQL） |
| Docker | 24+，`docker compose`（v2 语法）可用 |
| 域名 | 已解析到服务器 IP，已备案 |
| Supercell API Token | 已申请。**走 RoyaleAPI 代理时不用把服务器 IP 加白名单**，见下 |

### 关于 IP 白名单（RoyaleAPI 代理）

Supercell 的 key 绑定 IP 白名单，服务器换 IP / 用动态 IP 会直接 403。
本项目通过 **RoyaleAPI 的免费代理**绕开这一点：白名单里填**代理的 IP**，
请求发给代理，由它转发给官方。

`.env` 里两行就完成切换：

```bash
COC_API_TOKEN=你的token          # 还是你自己的 key，不经第三方保管
COC_BASE_URL=https://cocproxy.royaleapi.dev/v1
```

对应的 Supercell 后台操作：建 key 时 **Allowed IP 填 `45.79.218.79`**
（代理的 IP），**不要**填你服务器的 IP。

三点说明：

1. **路径与鉴权完全不变** —— 代理只换域名转发，`/v1/clans/%232PP` 原样到达官方，
   响应也是官方原样返回。所以错误码、reason、限流处理全部照旧。
2. **`COC_BASE_URL` 留空即走官方**。哪天拿到静态 IP，把这行删掉或清空即可切回，
   代码不用动。
3. **代理是共享服务，别把 `COC_RATE_LIMIT` 调高。** 默认 8 次/秒是保守值；
   代理由社区免费提供，放大速率等于把成本转嫁给运维它的人。

---

## 1. 拉代码并配置 `.env`

```bash
cd /opt/coc
git clone <你的仓库地址> .
cp .env.example .env
```

编辑 `.env`，**每一项都要填**：

```bash
# Supercell Token。绝不入库，只放这里
COC_API_TOKEN=你的token

POSTGRES_DB=coc
POSTGRES_USER=coc
POSTGRES_PASSWORD=生成的强密码

# 后台管理员（R3：只从环境变量读，不入库、无角色模型）
ADMIN_USERNAME=你的用户名
ADMIN_PASSWORD=生成的强密码

# session cookie 签名密钥。泄露等于任何人都能伪造管理员会话
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
ADMIN_SECRET_KEY=把上面生成的值粘进来

# 你的**备案域名**（不是公网 IP），不带 https://，也不带路径
PUBLIC_BASE_URL=api.example.com
```

**为什么必须是域名、不能填公网 IP：**

1. **小程序端只认域名。** 微信后台的 request 合法域名不接受 IP 地址，
   必须是 HTTPS + ICP 备案的域名。填了 IP，服务器一切正常但小程序调不通。
2. **nginx 靠它匹配请求。** 这个值经 compose 注入为 nginx 的 `SERVER_NAME`，
   成为 `server_name` 指令 —— 客户端 `Host` 头与它不一致的请求不会被正确路由。

它的消费方是 **nginx**（应用代码不读它）。本地开发随便填（如 `http://localhost:8000`），
只要非空 —— `Settings` 要求它存在。

验证：`.env` 已在 `.gitignore` 里（`git check-ignore .env` 应有输出）。

---

## 2. 启动

```bash
docker compose build
docker compose up -d
docker compose ps
```

确认三个服务都是 `running` 或 `healthy`。

**首次启动要建表**：

```bash
docker compose exec api alembic upgrade head
```

确认表已建（应看到 27 张表）：

```bash
docker compose exec api alembic current
```

---

## 3. 申请 HTTPS 证书

先用 HTTP 启动 nginx 完成验证，再签证书（certbot 需要能访问验证目录）。

```bash
mkdir -p deploy/certs deploy/certbot/www
docker compose run --rm --entrypoint "" certbot certonly \
  --webroot -w /var/www/certbot \
  -d api.example.com \
  --email your@example.com \
  --agree-tos --no-eff-email
```

把签出来的证书复制到 nginx 挂载的目录：

```bash
cp deploy/certbot/conf/live/api.example.com/fullchain.pem deploy/certs/
cp deploy/certbot/conf/live/api.example.com/privkey.pem  deploy/certs/
docker compose restart nginx
```

确认：

```bash
curl -I https://api.example.com/healthz     # 期望 200
```

---

## 4. 配置自动续签

```bash
chmod +x deploy/certbot-renew.sh deploy/backup.sh
```

宿主机 crontab（错开整点，避免与官方请求高峰撞在一起）：

```cron
17 3,15 * * * /opt/coc/deploy/certbot-renew.sh >> /var/log/certbot-renew.log 2>&1
17 4 * * * /opt/coc/deploy/backup.sh >> /var/log/coc-backup.log 2>&1
```

---

## 5. 导入升级数据

升级数据来自 npm 上的 MIT 开源数据集，**不调 Supercell API**，可以随便重跑：

```bash
docker compose exec api python -m app.cli import-game-data
```

期望输出 `2073` 行：troop 599 / spell 111 / hero 513 / equipment 850。

确认：

```bash
docker compose exec api python -c "
from app.db.session import engine
from sqlalchemy import text
import asyncio
async def main():
    async with engine.connect() as c:
        n = (await c.execute(text('SELECT count(*) FROM upgrade_items'))).scalar_one()
        print('upgrade_items 行数:', n)
    await engine.dispose()
asyncio.run(main())"
```

**不导入的话，升级相关接口全部返回空列表。**

---

## 6. 后台初始化

后台在 `https://api.example.com/admin/`，用 `.env` 里的 `ADMIN_USERNAME` /
`ADMIN_PASSWORD` 登录。

必做两件事：

1. **补翻译** ——「升级条目」里 `name_zh` 全是空的。导入阶段刻意不猜翻译
   （填了来源不明的翻译比留空更糟），只能人工补。
2. **录入第一条公告** ——「公告」里新建，`is_published` 勾上才会对外可见。

之后每天在这里处理投稿（「投稿」列表里只有「通过」「驳回」两个动作）。

---

## 7. 冒烟验证

```bash
# 存活与就绪
curl -s https://api.example.com/healthz     # {"status":"ok"}
curl -s https://api.example.com/readyz      # {"status":"ready"}

# 排行榜（只读库，不会消耗 Supercell 配额）
curl -s "https://api.example.com/api/v1/rankings/clans" | head -c 300

# 地区与联赛
curl -s "https://api.example.com/api/v1/locations" | head -c 200

# 公告
curl -s "https://api.example.com/api/v1/announcements" | head -c 200
```

**等采集跑完**（`APP_ROLE=all` 时调度器会在进程内跑，`rankings` 每 6 小时一次，
首次在下一个 cron 触发点）后，排行榜才有数据。在 `/api/v1/meta/freshness` 能看到
每个地区各类榜单的最后采集时间与采集任务的成败。

---

## 8. 配置小程序合法域名 ⚠️

**这一步漏掉，小程序端完全调不通。**

登录 [微信公众平台](https://mp.weixin.qq.com) → 开发管理 → 开发设置 → 服务器域名：

| 类型 | 填入 |
| --- | --- |
| request 合法域名 | `https://api.example.com` |
| uploadFile 合法域名 | `https://api.example.com` |
| downloadFile 合法域名 | `https://api.example.com` |

注意：

- **必须带 `https://`**，且**不能有路径**（填 `https://api.example.com/api` 会被拒绝）
- 域名需已备案，且在小程序后台配置过（未配置的域名无法使用）
- 证书必须是受信任的 CA 签发的，**自签证书一律不通过**
- 每月可修改的次数有限，改之前先确认好

配完后在小程序里真机预览一次，确认能拿到数据。

---

## 运维备忘

### 查看采集状态

```bash
curl -s https://api.example.com/api/v1/meta/freshness | python3 -m json.tool
```

`collectorRuns` 里 `status` 为 `partial` 表示部分地区/榜单采失败，
`failed` 表示全挂 —— 看 `detail` 里的明细定位是哪个地区。

### 手动触发一次采集

```bash
docker compose exec api python -c "
import asyncio
from app.cli import cmd_import_game_data
asyncio.run(cmd_import_game_data())"
```

### 日志

```bash
docker compose logs -f api          # 应用日志
docker compose logs -f nginx        # 访问日志
```

### 备份与恢复

```bash
/opt/coc/deploy/backup.sh                        # 手动跑一次
# 恢复：
gunzip -c backups/db-2026-10-10.sql.gz | \
  docker compose exec -T postgres psql -U coc -d coc
```

### 升级版本

```bash
git pull
docker compose build
docker compose up -d
docker compose exec api alembic upgrade head
```

---

## 单副本，不要加 worker

Dockerfile 的 `CMD` 固定 `--workers 1`，这不是保守，是硬性要求：

1. **令牌桶是进程内的。** 多 worker = 多个令牌桶，对 Supercell 的实际请求速率
   翻 N 倍，直接被限流。
2. **APScheduler 同理。** 多 worker 会让同一个采集 job 跑 N 遍。
3. **读时旁路缓存是进程内的**，多副本之间不共享。

要横向扩展，得先把限流、缓存、调度都换成共享实现（Redis / 独立采集进程）。
`APP_ROLE` 这个环境变量就是为拆分预留的。