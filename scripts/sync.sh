#!/bin/zsh
# Sync build-side object trees to R2.
#
# IMPORTANT: only the trees that stay resident locally (markdown, xml) may use
# `rclone sync`. The drained trees (pdf, reports, extracted-text) are moved to
# R2 and DELETED locally by drain.sh - a full-tree sync would interpret those
# deletions as intent and remove the objects from R2.
set -u
cd /Users/henrydashwood/git-legislation
source .envrc

export RCLONE_CONFIG_R2_TYPE=s3
export RCLONE_CONFIG_R2_PROVIDER=Cloudflare
export RCLONE_CONFIG_R2_ACCESS_KEY_ID=$R2_ACCESS_KEY_ID
export RCLONE_CONFIG_R2_SECRET_ACCESS_KEY=$R2_SECRET_ACCESS_KEY
export RCLONE_CONFIG_R2_ENDPOINT="${R2_URL%/*}"
export RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true

echo "[$(date '+%F %T')] syncing markdown and xml trees to R2"
for subtree in markdown xml; do
  rclone sync "var/object-store/legislation/$subtree" "r2:british-legislation/$subtree" \
    --transfers 16 --checkers 32 --log-level ERROR
  echo "[$(date '+%F %T')] $subtree synced"
done
echo "[$(date '+%F %T')] MARKDOWN+XML SYNC COMPLETE"
