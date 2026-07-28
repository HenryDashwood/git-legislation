#!/bin/zsh
# Remove R2 objects that no longer exist locally.
#
# This is the only script that deletes from R2, and it is never run by the daily
# poll. Before deleting anything it checks that the serving database does not
# still reference objects that are missing locally: that mismatch is exactly the
# state that produced the 2026-07-28 outage, when the object store had been
# re-keyed to .gz locally but PlanetScale still pointed at the old keys, and a
# mirroring sync deleted every key production was asking for.
#
# Usage: prune-r2.sh [--apply]     (dry run by default)
set -u
cd /Users/henrydashwood/git-legislation
source .envrc
export PATH="$HOME/.docker/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"

APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1

PSCALE_URL="${PSCALE_URL:-$(grep -o 'postgres[^"]*psdb\.cloud[^"]*' .envrc | head -1)}"
CONTAINER=git-legislation-postgres-1
SAMPLE_SIZE=300
# A stray missing object is normal (a drained or lost file); wholesale absence
# means the two sides disagree about key format, which is the dangerous case.
MISSING_TOLERANCE_PERCENT=2
log() { print -r -- "[$(date '+%F %T')] $*"; }

# --- preflight: would this delete something production still serves? ---
log "checking the serving database against the local object store"
keys=$(docker exec -i "$CONTAINER" psql "$PSCALE_URL" -t -A -c "
  select key from storage_objects
  where key like 'markdown/%' or key like 'xml/%'
  order by random() limit $SAMPLE_SIZE") || {
  log "ABORT: could not read the serving database; refusing to delete blind"
  exit 1
}

missing=0
total=0
missing_keys=()
while IFS= read -r key; do
  [[ -z "$key" ]] && continue
  total=$((total + 1))
  if [[ ! -f "var/object-store/legislation/$key" ]]; then
    missing=$((missing + 1))
    missing_keys+=("$key")
  fi
done <<< "$keys"

if (( total == 0 )); then
  log "ABORT: serving database returned no keys to check"
  exit 1
fi

percent=$(( missing * 100 / total ))
log "sampled $total serving keys; $missing missing locally (${percent}%)"
for key in ${missing_keys[@]:0:5}; do
  log "  missing: $key"
done

if (( percent > MISSING_TOLERANCE_PERCENT )); then
  log "ABORT: the serving database references objects this prune would delete."
  log "       Local and serving key formats have diverged - re-key the serving"
  log "       database (scripts/rekey-planetscale.sh) before pruning."
  exit 1
fi

export RCLONE_CONFIG_R2_TYPE=s3
export RCLONE_CONFIG_R2_PROVIDER=Cloudflare
export RCLONE_CONFIG_R2_ACCESS_KEY_ID=$R2_ACCESS_KEY_ID
export RCLONE_CONFIG_R2_SECRET_ACCESS_KEY=$R2_SECRET_ACCESS_KEY
export RCLONE_CONFIG_R2_ENDPOINT="${R2_URL%/*}"
export RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true

for subtree in markdown xml; do
  if (( APPLY )); then
    log "pruning $subtree"
    rclone sync "var/object-store/legislation/$subtree" "r2:british-legislation/$subtree" \
      --transfers 16 --checkers 32 --log-level ERROR
  else
    log "dry run for $subtree (pass --apply to delete)"
    # NOTICE-level logging is what reports the deletions a real run would make.
    deletions=$(rclone sync "var/object-store/legislation/$subtree" "r2:british-legislation/$subtree" \
      --transfers 16 --checkers 32 --log-level NOTICE --dry-run 2>&1 | grep -c 'Deleted' || true)
    log "  would delete $deletions objects from $subtree"
  fi
done
log "PRUNE COMPLETE"
