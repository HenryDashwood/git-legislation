#!/bin/zsh
# After the liteparse sweep completes: cache dynamic-only PDFs (the class
# legislation.gov.uk refuses to serve to Cloudflare Workers), then run the
# full catch-up (current-year ingestion, legal dates, R2 + PlanetScale sync).
set -u
export DB_URL="postgres://postgres:postgres@localhost:5433/british_legislation?sslmode=disable"
cd /Users/henrydashwood/git-legislation

BATCH=500
log() { print -r -- "[$(date '+%F %T')] $*"; }

log "waiting for SWEEP COMPLETE"
until grep -q 'SWEEP COMPLETE' var/liteparse-sweep/sweep.log 2>/dev/null; do
  sleep 600
done
log "sweep complete - caching dynamic-only PDFs"

iters=0
while (( iters < 100 )); do
  (( iters++ ))
  out=$(uv run git-legislation cache-dynamic-pdfs --limit $BATCH --delay-seconds 0.5 2>&1 | grep 'Scanned')
  log "batch[$iters]: $out"
  scanned=$(print -r -- "$out" | grep -o 'Scanned [0-9]*' | grep -o '[0-9]*')
  if [[ -z "${scanned:-}" || "$scanned" -lt "$BATCH" ]]; then
    break
  fi
done
log "DYNAMIC PDF CACHING COMPLETE"

log "running full catch-up"
zsh scripts/catch-up.sh
log "POST-SWEEP TASKS COMPLETE"
