#!/bin/zsh
# Step 1 of the compression cutover: upload the gzipped objects to R2 WITHOUT
# removing the uncompressed ones, so both key sets exist while the serving
# database still points at the old keys. `rclone copy` never deletes; using
# `sync` here would strip the old keys out from under production.
#
# Order for the whole cutover:
#   1. this script            (R2 gains .gz keys, old keys untouched)
#   2. deploy read-api        (understands both key sets, so safe to go early)
#   3. rekey-planetscale.sh   (serving database points at .gz keys)
#   4. prune old R2 keys      (removed once nothing references them)
set -u
cd /Users/henrydashwood/git-legislation
source .envrc

export RCLONE_CONFIG_R2_TYPE=s3
export RCLONE_CONFIG_R2_PROVIDER=Cloudflare
export RCLONE_CONFIG_R2_ACCESS_KEY_ID=$R2_ACCESS_KEY_ID
export RCLONE_CONFIG_R2_SECRET_ACCESS_KEY=$R2_SECRET_ACCESS_KEY
export RCLONE_CONFIG_R2_ENDPOINT="${R2_URL%/*}"
export RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true

echo "[$(date '+%F %T')] copying compressed markdown and xml trees to R2 (additive)"
for subtree in markdown xml; do
  rclone copy "var/object-store/legislation/$subtree" "r2:british-legislation/$subtree" \
    --transfers 16 --checkers 32 --log-level ERROR
  echo "[$(date '+%F %T')] $subtree copied"
done
echo "[$(date '+%F %T')] COMPRESSED COPY COMPLETE"
