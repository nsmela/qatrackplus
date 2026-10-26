#!/bin/bash
# Replace QATrack+'s database with a backup from /backups:
#   docker compose stop django django-q
#   docker compose run --rm --no-deps backup restore-db db_YYYYMMDD_HHMMSS.dump
#   docker compose up -d
#
# Based on the restore script by @leducvin in qatrackplus#866.
set -euo pipefail

BACKUP_DIR="/backups"
LOCK_FILE="$BACKUP_DIR/.qatrackplus-backup-restore.lock"
POSTGRES_HOST="postgres"
# The database restore-db connects to while it drops and recreates QATrack+'s:
# PostgreSQL cannot drop the database a connection is using.
MAINTENANCE_DB="postgres"

if [ "$#" -ne 1 ]; then
    echo "Usage: restore-db db_YYYYMMDD_HHMMSS.dump" >&2
    echo "The backups are listed by: docker compose exec backup ls -lh /backups" >&2
    exit 2
fi
backup_name=$1

# A file name in /backups only, not a path.
if [ "$(basename "$backup_name")" != "$backup_name" ]; then
    echo "Give the name of a file in $BACKUP_DIR, not a path." >&2
    exit 1
fi
case "$backup_name" in
    db_*.dump) ;;
    *)
        echo "Not a database backup: $backup_name (expected db_*.dump)." >&2
        exit 1
        ;;
esac
backup_file="$BACKUP_DIR/$backup_name"
if [ ! -f "$backup_file" ]; then
    echo "No such backup: $backup_file" >&2
    exit 1
fi

: "${POSTGRES_USER:?POSTGRES_USER is not set}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is not set}"
: "${POSTGRES_DB:?POSTGRES_DB is not set}"
case "$POSTGRES_DB" in
    postgres | template0 | template1)
        echo "Refusing to replace PostgreSQL's own database: $POSTGRES_DB" >&2
        exit 1
        ;;
esac

exec 9>"$LOCK_FILE"
if ! flock --nonblock 9; then
    echo "Another backup or restore is already running." >&2
    exit 1
fi

export PGPASSWORD="$POSTGRES_PASSWORD"

# Check everything that could fail before anything is changed.
echo "Checking the backup..."
pg_restore --list "$backup_file" >/dev/null
echo "Checking the connection to PostgreSQL..."
psql --host="$POSTGRES_HOST" --username="$POSTGRES_USER" --dbname="$MAINTENANCE_DB" \
    --no-psqlrc --tuples-only --command="SELECT 1;" >/dev/null

echo
echo "This permanently replaces the database \"$POSTGRES_DB\" with:"
echo "  $backup_file"
echo
echo "Stop QATrack+ first (docker compose stop django django-q): anyone still"
echo "connected is disconnected, and anything saved now is lost."
echo
printf 'Type the database name "%s" to continue: ' "$POSTGRES_DB"
read -r confirmation
if [ "$confirmation" != "$POSTGRES_DB" ]; then
    echo "Database restore cancelled; nothing was changed."
    exit 1
fi

echo "Replacing database $POSTGRES_DB..."
trap 'echo "The restore failed, and the database \"$POSTGRES_DB\" is now empty. Fix the problem above and run restore-db again." >&2' ERR
# --force disconnects anyone still connected rather than waiting for them.
dropdb --host="$POSTGRES_HOST" --username="$POSTGRES_USER" --maintenance-db="$MAINTENANCE_DB" \
    --if-exists --force "$POSTGRES_DB"
createdb --host="$POSTGRES_HOST" --username="$POSTGRES_USER" --maintenance-db="$MAINTENANCE_DB" \
    --owner="$POSTGRES_USER" --template=template0 "$POSTGRES_DB"

# --single-transaction: if anything fails, nothing is restored, rather than half
# a database. --no-owner: the restored tables belong to POSTGRES_USER, whatever
# user owned them where the backup was made.
pg_restore --host="$POSTGRES_HOST" --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" \
    --no-owner --single-transaction "$backup_file"

echo "Database restored. Start QATrack+ again with: docker compose up -d"
