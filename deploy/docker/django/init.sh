#!/bin/sh
# Run by compose.yaml's init service, as root, each time QATrack+ starts and
# before django does. QATrack+ runs as uid 1000, and installs from before 4.0.2
# ran it as root, so its volumes can hold root-owned files: this gives anything
# not already owned by QATrack+'s user to that user, then exits.
#
# QATRACK_MEDIA_DIR, QATRACK_LOGS_DIR and QATRACK_USER_DATA_DIR in .env can put
# a location in a folder on the server instead of a Docker volume. Handing over a
# folder cannot be undone, so, when any of them is set, this first refuses to
# start (and changes nothing) if:
#   - one location is inside another, or is the same folder (QATRACK_BACKUPS_DIR
#     included): the web server would show the logs or the secret key to anyone,
#     or the backups would be handed to QATrack+'s user;
#   - a folder is not empty and has no .qatrackplus-data file to mark it as
#     QATrack+'s. An empty folder is marked here, so a new site needs no step.
# Docker volumes are always QATrack+'s own, so they are never checked or marked,
# and a site that sets none of the variables works exactly as before.
#
# See "Keeping QATrack+'s data in folders on the server" in docs/install/docker.rst.
set -eu

uid=${QATRACK_UID:-1000}
gid=${QATRACK_GID:-1000}
marker=.qatrackplus-data
app=/usr/src/qatrackplus
media=$app/qatrack/media
static=$app/qatrack/static
user_data=$app/deploy/docker/user-data
logs=$app/logs
# Mounted read-only, only to check that nothing else is inside it.
backups=/backups

# The .env setting (or "") behind a location, and the volume or folder used
# when it is unset.
setting_of() {
    case $1 in
        "$media") echo QATRACK_MEDIA_DIR ;;
        "$user_data") echo QATRACK_USER_DATA_DIR ;;
        "$logs") echo QATRACK_LOGS_DIR ;;
        "$backups") echo QATRACK_BACKUPS_DIR ;;
        *) echo "" ;;
    esac
}
default_of() {
    case $1 in
        "$media") echo "the media-volume Docker volume" ;;
        "$static") echo "the static-volume Docker volume" ;;
        "$user_data") echo "the user-data-volume Docker volume" ;;
        "$logs") echo "the logs-volume Docker volume" ;;
        "$backups") echo "the backups folder beside compose.yaml" ;;
    esac
}
# The folder on the server set for a location, or "" for the default.
folder_of() {
    setting=$(setting_of "$1")
    if [ -n "$setting" ]; then printenv "$setting" || true; fi
}
# How a location is named in messages: its setting and folder, or its volume.
describe() {
    folder=$(folder_of "$1")
    if [ -n "$folder" ]; then echo "$(setting_of "$1")=$folder"; else default_of "$1"; fi
}

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
problems=$tmp/problems
: >"$problems"
to_mark=

uses_folders=
for location in "$media" "$user_data" "$logs" "$backups"; do
    if [ -n "$(folder_of "$location")" ]; then uses_folders=yes; fi
done

if [ -n "$uses_folders" ]; then
    # Folders are compared by what they are on disk (device and inode), not by
    # the paths in .env, so relative paths such as ./backups and symbolic links
    # are handled too. A folder nested further down, on another disk mounted
    # inside a location, is not looked for (find -xdev).
    roots=$tmp/roots
    : >"$roots"
    for location in "$media" "$static" "$user_data" "$logs" "$backups"; do
        if [ -d "$location" ]; then
            printf '%s %s\n' "$(stat -c %d:%i "$location")" "$location" >>"$roots"
        fi
    done
    # The same folder used for two locations.
    awk 'seen[$1] { print seen[$1], $2 } { seen[$1] = $2 }' "$roots" |
        while read -r first second; do
            echo "$(describe "$second") is the same folder as $(describe "$first")." >>"$problems"
        done
    # One location inside another.
    while read -r _ outer; do
        find "$outer" -xdev -mindepth 1 -type d -printf '%D:%i\n' |
            awk -v roots="$roots" '
                BEGIN { while ((getline line < roots) > 0) { split(line, f, " "); inner[f[1]] = f[2] } }
                $1 in inner { print inner[$1] }' |
            while read -r inner; do
                echo "$(describe "$inner") is inside $(describe "$outer")." >>"$problems"
            done
    done <"$roots"
    if [ -s "$problems" ]; then
        cat >>"$problems" <<EOF
Give each of these locations a folder of its own, side by side, not one
inside another: the web server shows everything in the media folder to
anyone, and everything in the media, logs and user-data folders is given
to the QATrack+ user.
EOF
    fi

    # Folders that are not empty must already be marked as QATrack+'s.
    for location in "$media" "$user_data" "$logs"; do
        folder=$(folder_of "$location")
        if [ -z "$folder" ]; then continue; fi
        if [ -f "$location/$marker" ] && [ ! -h "$location/$marker" ]; then continue; fi
        if [ -z "$(ls -A "$location")" ]; then
            to_mark="$to_mark $location"
            continue
        fi
        cat >>"$problems" <<EOF
$(setting_of "$location")=$folder
is not empty, and has no $marker file to mark it as QATrack+'s.
Each time QATrack+ starts it gives everything in its folders to its own user
(uid $uid), which cannot be undone, so it will not use a folder that may hold
anyone else's files. Choose an empty folder (Docker creates one that does not
exist yet). If this folder holds only QATrack+'s own data, copied from its
volume for example, mark it with:
    sudo touch $folder/$marker
EOF
    done
fi

if [ -s "$problems" ]; then
    {
        echo "QATrack+ did not start, and nothing was changed:"
        echo
        cat "$problems"
        echo
        echo "Fix .env and run docker compose up -d again. See \"Keeping QATrack+'s data in"
        echo "folders on the server\" in docs/install/docker.rst."
    } >&2
    exit 1
fi

for location in $to_mark; do
    cat >"$location/$marker" <<EOF
This folder holds QATrack+'s data ($(setting_of "$location") in deploy/docker/.env).
Each time QATrack+ starts, it gives everything in this folder to its own user.
Keep this file: without it, QATrack+ will not start with this folder.
EOF
    echo "Marked $(describe "$location") as QATrack+'s ($marker)."
done

# chown -h re-owns a symbolic link itself, never the file it points to (which
# may be outside the folder, or missing). -xdev keeps find off any other disk
# mounted inside a location: only the folder it is mounted on is re-owned,
# nothing on that disk.
for location in "$media" "$static" "$user_data" "$logs"; do
    find "$location" -xdev \( ! -user "$uid" -o ! -group "$gid" \) \
        -printf . -exec chown -h "$uid:$gid" {} + >"$tmp/count"
    echo "Re-owned to $uid:$gid in $(describe "$location"): $(wc -c <"$tmp/count")"
done
