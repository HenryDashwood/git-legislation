#!/bin/zsh
# Mirror the local object store to the R2 bucket. Idempotent: re-run to pick
# up files produced after the previous pass (e.g. by the liteparse sweep).
set -u
cd /Users/henrydashwood/git-legislation
source .envrc

export RCLONE_CONFIG_R2_TYPE=s3
export RCLONE_CONFIG_R2_PROVIDER=Cloudflare
export RCLONE_CONFIG_R2_ACCESS_KEY_ID=$R2_ACCESS_KEY_ID
export RCLONE_CONFIG_R2_SECRET_ACCESS_KEY=$R2_SECRET_ACCESS_KEY
export RCLONE_CONFIG_R2_ENDPOINT="${R2_URL%/*}"
export RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true

echo "[$(date '+%F %T')] R2 sync starting"
rclone sync var/object-store/legislation r2:british-legislation \
  --transfers 16 \
  --checkers 32 \
  --stats 5m \
  --stats-one-line \
  --log-level NOTICE
rc=$?
echo "[$(date '+%F %T')] R2 SYNC COMPLETE rc=$rc"
