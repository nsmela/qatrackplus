#!/bin/bash
# Back up QATrack+'s database and uploaded files into /backups (deploy/docker/backups
# on the host). Runs nightly from cron; run it by hand with
#   docker compose exec backup backup
#
# Based on the backup script by @leducvin in qatrackplus#866.
set -euo pipefail

BACKUP_DIR="/backups"
MEDIA_DIR="/media"
LOCK_FILE="$BACKUP_DIR/.qatrackplus-backup-restore.lock"

# How long the backup archives are kept. This deletes only the db_*.dump and
# media_*.tar.gz files this script writes. Never point anything like it at the
# media folder: uploads are part of QATrack+'s records, and nothing in QATrack+
# deletes one.
RETENTION_DAYS=7

mkdir -p "$BACKUP_DIR"

# One backup or restore at a time: a restore must not run while a backup reads
# the database, and the nightly backup must not start during a restore.
exec 9>"$LOCK_FILE"
if ! flock --nonblock 9; then
    echo "Another backup or restore is already running." >&2
    exit 1
fi

DATE=$(date +%Y%m%d_%H%M%S)
dump_file="$BACKUP_DIR/db_$DATE.dump"
media_file="$BACKUP_DIR/media_$DATE.tar.gz"

# Each archive is written under a .tmp name and renamed only once it is complete
# and readable, so an interrupted backup never leaves a file that looks finished.
cleanup() {
    rm -f "$dump_file.tmp" "$media_file.tmp"
}
trap cleanup EXIT

echo "Starting backup at $DATE"

export PGPASSWORD="$POSTGRES_PASSWORD"

echo "Dumping the database..."
# --lock-wait-timeout: give up rather than wait forever behind a conflicting lock.
pg_dump \
    --host=postgres \
    --username="$POSTGRES_USER" \
    --dbname="$POSTGRES_DB" \
    --format=custom \
    --lock-wait-timeout=60s \
    --file="$dump_file.tmp"
pg_restore --list "$dump_file.tmp" >/dev/null
mv "$dump_file.tmp" "$dump_file"
echo "Database saved to $dump_file"

echo "Archiving uploaded files..."
# Entries are media/..., the same layout as backups made by QATrack+ 4.0.
tar --create --gzip --file="$media_file.tmp" --directory=/ "${MEDIA_DIR#/}"
tar --list --gzip --file="$media_file.tmp" >/dev/null
mv "$media_file.tmp" "$media_file"
echo "Uploaded files saved to $media_file"

trap - EXIT

find "$BACKUP_DIR" -maxdepth 1 -type f -name "db_*.dump" -mtime +$RETENTION_DAYS -delete
find "$BACKUP_DIR" -maxdepth 1 -type f -name "media_*.tar.gz" -mtime +$RETENTION_DAYS -delete

echo "Backup completed successfully"
