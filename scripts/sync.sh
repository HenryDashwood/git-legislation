#!/bin/zsh
# Upload build-side object trees to R2. Additive only: this never deletes.
#
# It used to run `rclone sync`, which mirrors deletions. That made the daily
# poll capable of removing objects the serving database still referenced — and
# on 2026-07-28 it did exactly that, taking content endpoints down for five
# hours after the object store was re-keyed to .gz locally. Deleting from R2 is
# now a separate, deliberate step: scripts/prune-r2.sh, which refuses to run if
# the serving database still points at anything it would remove.
#
# The cost of copy-only is that renamed or removed objects linger in R2 until a
# prune. That is cheap; the alternative cost is an outage.
set -u
cd /Users/henrydashwood/git-legislation
source .envrc

export RCLONE_CONFIG_R2_TYPE=s3
export RCLONE_CONFIG_R2_PROVIDER=Cloudflare
export RCLONE_CONFIG_R2_ACCESS_KEY_ID=$R2_ACCESS_KEY_ID
export RCLONE_CONFIG_R2_SECRET_ACCESS_KEY=$R2_SECRET_ACCESS_KEY
export RCLONE_CONFIG_R2_ENDPOINT="${R2_URL%/*}"
export RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true

echo "[$(date '+%F %T')] copying markdown and xml trees to R2 (additive)"
for subtree in markdown xml; do
  rclone copy "var/object-store/legislation/$subtree" "r2:british-legislation/$subtree" \
    --transfers 16 --checkers 32 --log-level ERROR
  echo "[$(date '+%F %T')] $subtree copied"
done
echo "[$(date '+%F %T')] MARKDOWN+XML SYNC COMPLETE"
