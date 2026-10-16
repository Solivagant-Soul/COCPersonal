#!/usr/bin/env bash
# 续签证书并重载 nginx。
#
# certbot 的 renew 只在证书快到期时才真正续签，所以要靠 systemd timer
# 或宿主机 crontab 定期跑（建议每天两次）。renew 是幂等的：
# 没到期就直接退出，不会打扰线上。
#
# 宿主机 crontab 示例：
#   17 3,15 * * * /opt/coc/deploy/certbot-renew.sh >> /var/log/certbot-renew.log 2>&1

set -euo pipefail

echo "[$(date -u +%FT%TZ)] 开始续签"

# webroot 模式：不启动独立的 certbot 容器，直接用 nginx 里的验证目录
docker compose exec -T certbot certbot renew \
    --webroot -w /var/www/certbot \
    --quiet

# 只有真的换了证书才重载，避免每次都 reload 打断长连接
docker compose exec -T nginx nginx -s reload

echo "[$(date -u +%FT%TZ)] 完成"