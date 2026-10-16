#!/usr/bin/env bash
# 备份数据库与媒体目录。
#
# 不清理的话备份会把磁盘吃满 —— 而磁盘满的直接后果是**数据库写不进去**，
# 现象是"服务看着正常但数据不再更新"，比没有备份更难排查。
#
# 宿主机 crontab 示例（每天 04:17，错开整点）：
#   17 4 * * * /opt/coc/deploy/backup.sh >> /var/log/coc-backup.log 2>&1

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/coc/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
STAMP="$(date +%F)"

mkdir -p "$BACKUP_DIR"

echo "[$(date -u +%FT%TZ)] 备份数据库"
# --clean --if-exists 让重复备份可覆盖，不会因对象已存在而失败
docker compose exec -T postgres \
    pg_dump -U "${POSTGRES_USER:-coc}" -d "${POSTGRES_DB:-coc}" --clean --if-exists \
    > "$BACKUP_DIR/db-$STAMP.sql"

gzip -f "$BACKUP_DIR/db-$STAMP.sql"

echo "[$(date -u +%FT%TZ)] 备份媒体目录"
docker run --rm \
    -v coc-backend_media:/data:ro \
    -v "$BACKUP_DIR":/backup \
    alpine tar czf "/backup/media-$STAMP.tar.gz" -C /data .

echo "[$(date -u +%FT%TZ)] 清理 $RETENTION_DAYS 天前的备份"
# 只删本脚本生成的 db-*.sql.gz 与 media-*.tar.gz，
# 不碰目录里的其他文件（误删备份比不清理严重得多）
find "$BACKUP_DIR" -maxdepth 1 -type f \
    \( -name 'db-*.sql.gz' -o -name 'media-*.tar.gz' \) \
    -mtime "+$RETENTION_DAYS" -print -delete

echo "[$(date -u +%FT%TZ)] 完成，备份目录: $BACKUP_DIR"