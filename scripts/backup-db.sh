#!/usr/bin/env bash
# Monthly logical backup for the MySQL service managed by docker-compose.yml.
# Keep this script on the Docker host. It deliberately uses a logical dump,
# which is portable and does not require stopping the bot or MySQL.

set -Eeuo pipefail

readonly PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backup}"
readonly RETENTION_DAYS="${RETENTION_DAYS:-370}"
readonly COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"
readonly LOCK_FILE="${BACKUP_DIR}/.mysql-backup.lock"

mkdir -p -- "$BACKUP_DIR"

# Do not allow a second dump to overlap with a slow or manually started dump.
exec 9>"$LOCK_FILE"
flock -n 9 || {
  echo "$(date -Is) WARNING: a database backup is already running" >&2
  exit 0
}

timestamp="$(date +%Y-%m-%d_%H-%M-%S)"
backup_file="$BACKUP_DIR/reminder_bot_${timestamp}.sql.gz"
temp_file="${backup_file}.tmp"

cleanup() {
  rm -f -- "$temp_file"
}
trap cleanup EXIT

cd -- "$PROJECT_DIR"

# MYSQL_ROOT_PASSWORD exists only inside the db container. MYSQL_PWD keeps it
# out of the mysqldump command arguments and the host shell never expands it.
docker compose -f "$COMPOSE_FILE" exec -T db sh -c '
  export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"
  exec mysqldump \
    --user=root \
    --single-transaction \
    --quick \
    --routines \
    --events \
    --triggers \
    --databases "$MYSQL_DATABASE"
' | gzip -c > "$temp_file"

mv -- "$temp_file" "$backup_file"
trap - EXIT

# Keep roughly twelve monthly backups. Deletion only happens after a successful
# new backup; set RETENTION_DAYS to adjust this V1 retention policy.
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'reminder_bot_*.sql.gz' -mtime "+$RETENTION_DAYS" -delete

echo "$(date -Is) INFO: database backup completed: $backup_file"
