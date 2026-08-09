#!/bin/bash
# Backfill loop for the Hetzner worker.
#
# Writes rows straight to the serving database (DB_URL) and copies objects to R2
# as it goes, so there is no local Postgres and no sync step — the same
# simplification the remote poll gets. Objects are copied, never synced: see
# scripts/prune-r2.sh for why deletion stays a deliberate local operation.
#
# The backfill command skips version dates already present, so this loop is safe
# to restart at any point and safe to run to completion repeatedly.
set -u
cd /opt/git-legislation
export PATH="$HOME/.local/bin:$PATH"

LIST="${BACKFILL_LIST:-scripts/backfill-acts.txt}"
SYNC_EVERY_SECONDS="${SYNC_EVERY_SECONDS:-3600}"

log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }

copy_objects_to_r2() {
  export RCLONE_CONFIG_R2_TYPE=s3
  export RCLONE_CONFIG_R2_PROVIDER=Cloudflare
  export RCLONE_CONFIG_R2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID"
  export RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
  export RCLONE_CONFIG_R2_ENDPOINT="${R2_URL%/*}"
  export RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true
  for subtree in markdown xml; do
    [ -d "var/object-store/legislation/$subtree" ] || continue
    rclone copy "var/object-store/legislation/$subtree" \
      "r2:british-legislation/$subtree" --transfers 8 --checkers 16 --log-level ERROR
  done
}

# Ship objects on a timer rather than at the end: a multi-day crawl should not
# hold days of work on one box's disk.
(
  while true; do
    sleep "$SYNC_EVERY_SECONDS"
    log "periodic object copy to R2"
    copy_objects_to_r2 && log "object copy done"
  done
) &
SYNC_PID=$!
trap 'kill "$SYNC_PID" 2>/dev/null' EXIT

log "backfill starting from $LIST"
uv run git-legislation backfill-document-versions --from-file "$LIST"
status=$?
log "backfill command exited with status $status"

log "final object copy to R2"
copy_objects_to_r2
log "BACKFILL RUN COMPLETE"
exit "$status"
