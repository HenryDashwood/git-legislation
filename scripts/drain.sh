#!/bin/zsh
# Continuously drain bulky write-once artifacts (PDFs, liteparse reports) to
# R2, deleting the local copy after checksum-verified upload. Keeps local disk
# usage bounded while the liteparse sweep runs. xml/ and markdown/ stay local
# (needed for fast converter re-renders) and are synced separately.
set -u
cd /Users/henrydashwood/git-legislation
source .envrc

export RCLONE_CONFIG_R2_TYPE=s3
export RCLONE_CONFIG_R2_PROVIDER=Cloudflare
export RCLONE_CONFIG_R2_ACCESS_KEY_ID=$R2_ACCESS_KEY_ID
export RCLONE_CONFIG_R2_SECRET_ACCESS_KEY=$R2_SECRET_ACCESS_KEY
export RCLONE_CONFIG_R2_ENDPOINT="${R2_URL%/*}"
export RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true

log() { print -r -- "[$(date '+%F %T')] $*"; }

# Wait for the initial bulk sync to finish so the two jobs never race on the
# same files.
until grep -q 'R2 SYNC COMPLETE' var/r2-sync/sync.log 2>/dev/null; do
  sleep 300
done
log "bulk sync complete - drain loop starting"

while true; do
  for subtree in pdf reports extracted-text; do
    src="var/object-store/legislation/$subtree"
    [[ -d "$src" ]] || continue
    moved=$(rclone move "$src" "r2:british-legislation/$subtree" \
      --min-age 30m \
      --delete-empty-src-dirs \
      --transfers 8 \
      --log-level ERROR 2>&1 | tail -5)
    [[ -n "$moved" ]] && log "$subtree move output: $moved"
  done
  log "drain pass done: pdf=$(du -sh var/object-store/legislation/pdf 2>/dev/null | cut -f1) reports=$(du -sh var/object-store/legislation/reports 2>/dev/null | cut -f1) disk_free=$(df -h / | tail -1 | awk '{print $4}')"
  sleep 600
done
