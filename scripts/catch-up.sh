#!/bin/zsh
# Idempotent catch-up: pick up legislation published since the last run.
#
# Re-enumerates the current year for every active series and publishes
# anything new or changed (content-addressed versions make re-runs free),
# then extracts legal dates, syncs content objects to R2, and delta-syncs
# rows to PlanetScale. Run weekly, or whenever the feed should be fresh.
# Interim mechanism until Publication Log polling exists.
set -u
export DB_URL="postgres://postgres:postgres@localhost:5433/british_legislation?sslmode=disable"
cd /Users/henrydashwood/git-legislation

if pgrep -f 'liteparse-sweep/sweep.sh' > /dev/null && [[ "${FORCE:-0}" != "1" ]]; then
  print -r -- "The liteparse sweep is running; catch-up would compete for legislation.gov.uk rate limits."
  print -r -- "Re-run with FORCE=1 to override, or wait for the sweep to finish."
  exit 1
fi

AT=$(date '+%Y-%m-%d')
YEARS=($(date '+%Y'))
if [[ $(date '+%m') == "01" ]]; then
  YEARS+=($(( ${YEARS[1]} - 1 )))
fi

# Series still producing documents (closed historical series excluded).
ACTIVE_TYPES=(ukpga ukla ukppa uksi ukcm nisro nisi nisr asp ssi wsi nia mwa anaw ukci asc ukmo)

log() { print -r -- "[$(date '+%F %T')] $*"; }

log "catch-up starting: at=$AT years=${YEARS[*]}"
for year in "${YEARS[@]}"; do
  for legislation_type in "${ACTIVE_TYPES[@]}"; do
    log "ingesting $legislation_type $year"
    uv run git-legislation ingest-point-in-time-year "$legislation_type" "$year" --at "$AT" 2>&1 | tail -1
  done
done

log "extracting legal dates"
uv run git-legislation extract-legal-dates 2>&1 | tail -2

log "syncing content objects to R2"
zsh scripts/sync.sh 2>&1 | tail -1

log "delta-syncing rows to PlanetScale"
zsh scripts/delta-sync-planetscale.sh "$(date -v-7d '+%Y-%m-%d')" 2>&1 | tail -2

log "CATCH-UP COMPLETE"
