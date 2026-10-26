#!/bin/bash
# Replace QATrack+'s uploaded files with a backup from /backups:
#   docker compose stop django django-q
#   docker compose run --rm --no-deps backup restore-media media_YYYYMMDD_HHMMSS.tar.gz
#   docker compose up -d
#
# Based on the restore script by @leducvin in qatrackplus#866.
set -euo pipefail

BACKUP_DIR="/backups"
MEDIA_DIR="/media"
LOCK_FILE="$BACKUP_DIR/.qatrackplus-backup-restore.lock"

if [ "$#" -ne 1 ]; then
    echo "Usage: restore-media media_YYYYMMDD_HHMMSS.tar.gz" >&2
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
    media_*.tar.gz) ;;
    *)
        echo "Not an uploaded-files backup: $backup_name (expected media_*.tar.gz)." >&2
        exit 1
        ;;
esac
backup_file="$BACKUP_DIR/$backup_name"
if [ ! -f "$backup_file" ]; then
    echo "No such backup: $backup_file" >&2
    exit 1
fi
if [ ! -w "$MEDIA_DIR" ]; then
    echo "$MEDIA_DIR is not writable." >&2
    exit 1
fi

exec 9>"$LOCK_FILE"
if ! flock --nonblock 9; then
    echo "Another backup or restore is already running." >&2
    exit 1
fi

# Unpack into a staging folder on the same volume first, so a damaged archive
# is found before any current file is touched.
staging=$(mktemp -d "$MEDIA_DIR/.restore.XXXXXX")
trap 'rm -rf "$staging"' EXIT

echo "Checking the backup..."
tar --list --gzip --file="$backup_file" >"$staging/archive.list"
# Backups made by QATrack+ hold media/... and nothing else. Refuse anything
# else, including absolute paths and .. components.
if ! grep -Eq '^media/?$' "$staging/archive.list" \
    || grep -Evq '^media(/|$)' "$staging/archive.list" \
    || grep -Eq '(^|/)\.\.(/|$)' "$staging/archive.list"; then
    echo "$backup_name is not a QATrack+ uploaded-files backup: its entries must all be under media/." >&2
    exit 1
fi
mkdir "$staging/extracted"
tar --extract --gzip --file="$backup_file" --directory="$staging/extracted"

echo
echo "This permanently replaces every uploaded file in QATrack+ with:"
echo "  $backup_file"
echo
echo "Stop QATrack+ first (docker compose stop django django-q), so nothing is"
echo "uploaded while the files are replaced."
echo
printf 'Type RESTORE to continue: '
read -r confirmation
if [ "$confirmation" != "RESTORE" ]; then
    echo "Restore of uploaded files cancelled; nothing was changed."
    exit 1
fi

echo "Replacing uploaded files..."
find "$MEDIA_DIR" -mindepth 1 -maxdepth 1 ! -path "$staging" -exec rm -rf -- {} +
cp -a "$staging/extracted/media/." "$MEDIA_DIR/"

echo "Uploaded files restored. Start QATrack+ again with: docker compose up -d"
echo "(its init service gives the restored files to the QATrack+ user)."
