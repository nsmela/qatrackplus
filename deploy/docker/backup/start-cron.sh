#!/bin/bash
# Start crond, which runs the nightly backup at 2 AM (see the Dockerfile), and
# say in `docker compose logs backup` which time zone that 2 AM is in.
#
# compose.yaml sets TZ from TIME_ZONE in .env, the same setting QATrack+ uses,
# and to QATrack+'s own default when TIME_ZONE is not set. crond's schedule and
# the date and time in each backup's file name both follow TZ.
set -euo pipefail

zone=${TZ:-}
if [ -z "$zone" ]; then
    echo "Warning: TZ is not set, so backups run at 2 AM UTC and are named in UTC." >&2
    echo "Start the backup service with docker compose, which sets it from TIME_ZONE in .env." >&2
elif [ ! -f "/usr/share/zoneinfo/${zone#:}" ]; then
    # The C library does not complain about a zone it does not know: it quietly
    # uses UTC instead.
    echo "Warning: \"$zone\" is not a time zone this container knows, so backups run" >&2
    echo "at 2 AM UTC and are named in UTC. Set TIME_ZONE in .env to a name from the" >&2
    echo "tz database, such as America/Toronto, then run: docker compose up -d" >&2
else
    echo "Backups run every night at 2 AM, $zone time (it is now $(date '+%Y-%m-%d %H:%M %Z'))."
fi
# compose.yaml derives TZ from TIME_ZONE when it reads .env. Should they ever
# differ (TIME_ZONE also set in the shell that ran docker compose, say), the
# backups and QATrack+ would be on different clocks.
if [ -n "${TIME_ZONE:-}" ] && [ "$TIME_ZONE" != "$zone" ]; then
    echo "Warning: backups use TZ=$zone, but TIME_ZONE is $TIME_ZONE." >&2
fi

exec crond -f -d 8
