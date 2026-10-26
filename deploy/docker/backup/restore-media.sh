#!/bin/bash
# Replace QATrack+'s uploaded files with a backup from /backups:
#   docker compose stop django django-q
#   docker compose run --rm --no-deps -v media-volume:/media-writable backup \
#       restore-media media_YYYYMMDD_HHMMSS.tar.gz
#   docker compose up -d
#
# The backup service mounts the uploaded files read-only at /media, since the
# nightly backup only reads them. -v mounts the same volume again, writable, for
# this one command.
#
# Based on the restore script by @leducvin in qatrackplus#866.
set -euo pipefail

BACKUP_DIR="/backups"
# The media volume, as the backup service mounts it (read-only).
MEDIA_DIR="/media"
# The same volume, mounted writable for this command by docker compose run -v.
TARGET_DIR="/media-writable"
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
# TARGET_DIR must be the very volume the backup service backs up, not a new,
# empty one made by a mistyped volume name: the same volume mounted twice has the
# same device and inode at both mount points.
if [ ! -d "$TARGET_DIR" ] || [ ! -w "$TARGET_DIR" ] \
    || [ "$(stat -c '%d:%i' "$TARGET_DIR")" != "$(stat -c '%d:%i' "$MEDIA_DIR")" ]; then
    echo "The uploaded files are not mounted writable at $TARGET_DIR. Run restore-media with" >&2
    echo "  docker compose run --rm --no-deps -v media-volume:$TARGET_DIR backup restore-media $backup_name" >&2
    exit 1
fi

exec 9>"$LOCK_FILE"
if ! flock --nonblock 9; then
    echo "Another backup or restore is already running." >&2
    exit 1
fi

for leftover in "$TARGET_DIR"/.restore.*; do
    if [ -e "$leftover" ]; then
        echo "Note: ${leftover#"$TARGET_DIR"/} in the media volume is left over from a restore that was" >&2
        echo "stopped part way, and is left alone. It may hold the uploaded files from before" >&2
        echo "that restore: check what is in it before you delete it." >&2
    fi
done

# Unpack into a staging folder on the same volume first, so a damaged archive
# is found before any current file is touched, and so the files can be swapped
# by renaming them rather than copying. backup leaves .restore.* out of backups.
staging=$(mktemp -d "$TARGET_DIR/.restore.XXXXXX")
stage=checking
on_exit() {
    local status=$?
    trap - EXIT INT TERM
    if [ "$stage" = setting_aside ] || [ "$stage" = replacing ]; then
        echo >&2
        if put_back; then
            echo "The restore did not finish. The uploaded files were put back as they were." >&2
        else
            echo "The restore did not finish, and the uploaded files could not all be put back." >&2
            echo "The files from before the restore are in $staging/previous (the media volume's" >&2
            echo "${staging#"$TARGET_DIR"/}/previous folder). Ask for help before running restore-media again." >&2
            exit "$status"
        fi
    fi
    rm -rf "$staging"
    exit "$status"
}
trap on_exit EXIT
# Ctrl-C or docker stop: stop here, and let on_exit tidy up.
trap 'exit 130' INT
trap 'exit 143' TERM

# Move every entry directly inside $1 into $2, dot-files included. .restore.*
# folders (this restore's staging folder, or one left by a restore that was
# killed outright) are never moved.
move_entries() {
    local entry
    find "$1" -mindepth 1 -maxdepth 1 ! -name '.restore.*' -print0 |
        while IFS= read -r -d '' entry; do
            mv -- "$entry" "$2/"
        done
}

# Undo a replacement that stopped part way: remove what had come from the backup
# (it is all still in the backup file), then move the earlier files back.
put_back() {
    if [ "$stage" = replacing ]; then
        find "$TARGET_DIR" -mindepth 1 -maxdepth 1 ! -name '.restore.*' -exec rm -rf -- {} + || return 1
    fi
    move_entries "$staging/previous" "$TARGET_DIR"
}

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
mkdir "$staging/extracted" "$staging/previous"
# A backup made before backup left out restore-media's staging folders may hold
# one; it is not part of the uploaded files.
tar --extract --gzip --file="$backup_file" --directory="$staging/extracted" \
    --anchored --exclude='media/.restore.*'

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
# Renames within one volume: each move is instant, and needs no space beyond the
# unpacked backup. The current files are set aside first, so a restore that stops
# part way can put them back.
stage=setting_aside
move_entries "$TARGET_DIR" "$staging/previous"
stage=replacing
move_entries "$staging/extracted/media" "$TARGET_DIR"
stage=finished
rm -rf "$staging"

echo "Uploaded files restored. Start QATrack+ again with: docker compose up -d"
echo "(its init service gives the restored files to the QATrack+ user)."
