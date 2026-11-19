#!/usr/bin/env bash
# Remove one-time reminders that have already passed and are no longer active.
#
# V1 trade-off: the schema has no sent_at column. A past, inactive, one-time
# reminder is treated as completed. This also removes a one-time reminder that
# was manually cancelled after its scheduled time. Do not use this script for
# audit retention; keep the regular database backups instead.
#
# Observability: logs only event name and aggregate candidate/deleted counts.
# It deliberately never logs reminder text, user IDs, or database credentials.
#
# The 1-day margin avoids a timezone mismatch: the bot stores Asia/Ho_Chi_Minh
# local time while MySQL NOW() inside the db container is UTC.

set -Eeuo pipefail

readonly PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backup}"
readonly COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"
readonly LOCK_FILE="$BACKUP_DIR/.cleanup-expired-one-time-reminders.lock"

mode="${1:---dry-run}"
if [[ "$mode" != "--dry-run" && "$mode" != "--execute" ]]; then
  echo "Usage: $0 [--dry-run|--execute]" >&2
  exit 2
fi

log() {
  local level="$1"
  shift
  echo "$(date -Is) $level $*"
}

mkdir -p -- "$BACKUP_DIR"
exec 9>"$LOCK_FILE"
flock -n 9 || {
  log WARNING "event=expired_one_time_cleanup_skipped reason=already_running"
  exit 0
}

cd -- "$PROJECT_DIR"

run_mysql() {
  docker compose -f "$COMPOSE_FILE" exec -T db sh -c '
    export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"
    exec mysql --user=root --batch --skip-column-names "$MYSQL_DATABASE"
  '
}

candidate_count="$(run_mysql <<'SQL'
SELECT COUNT(*)
FROM reminders
WHERE repeat_type = 'none'
  AND is_active = FALSE
  AND remind_at < DATE_SUB(NOW(), INTERVAL 1 DAY);
SQL
)"

if [[ ! "$candidate_count" =~ ^[0-9]+$ ]]; then
  log ERROR "event=expired_one_time_cleanup_failed reason=invalid_candidate_count"
  exit 1
fi

if [[ "$mode" == "--dry-run" ]]; then
  log INFO "event=expired_one_time_cleanup_preview candidate_count=$candidate_count"
  exit 0
fi

# The scheduled job runs the day after the monthly backup. Refuse deletion when
# no recent local backup exists, so a failed backup cannot silently precede data
# removal. This is a V1 guard; off-host backup replication is out of scope.
if ! find "$BACKUP_DIR" -maxdepth 1 -type f -name 'reminder_bot_*.sql.gz' -mtime -2 -print -quit | grep -q .; then
  log ERROR "event=expired_one_time_cleanup_failed reason=no_recent_backup"
  exit 1
fi

deleted_count="$(run_mysql <<'SQL'
START TRANSACTION;
DELETE FROM reminders
WHERE repeat_type = 'none'
  AND is_active = FALSE
  AND remind_at < DATE_SUB(NOW(), INTERVAL 1 DAY);
SELECT ROW_COUNT();
COMMIT;
SQL
)"

if [[ ! "$deleted_count" =~ ^[0-9]+$ ]]; then
  log ERROR "event=expired_one_time_cleanup_failed reason=invalid_deleted_count"
  exit 1
fi

log INFO "event=expired_one_time_cleanup_completed candidate_count=$candidate_count deleted_count=$deleted_count"
