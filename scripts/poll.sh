#!/bin/zsh
# Daily Publication Log poll: ingest every document with a new XML publication
# event since the stored cursor, then push the results to the serving copies.
#
# The poll command itself is location-agnostic (the cursor lives in whichever
# database DB_URL targets); this wrapper is the local-Mac deployment of it,
# targeting the local build database and then syncing R2 + PlanetScale.
# Scheduled via launchd: ~/Library/LaunchAgents/com.henrydashwood.git-legislation.poll.plist
set -u
export DB_URL="postgres://postgres:postgres@localhost:5433/british_legislation?sslmode=disable"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$HOME/.docker/bin:/Applications/Docker.app/Contents/Resources/bin:/usr/local/bin:$PATH"
cd /Users/henrydashwood/git-legislation

log() { print -r -- "[$(date '+%F %T')] $*"; }

if pgrep -f 'liteparse-sweep/sweep.sh' > /dev/null && [[ "${FORCE:-0}" != "1" ]]; then
  log "liteparse sweep is running; skipping poll to avoid competing for rate limits (FORCE=1 overrides)"
  exit 0
fi

if ! docker exec git-legislation-postgres-1 pg_isready -q -U postgres -d british_legislation 2>/dev/null; then
  log "local Postgres container is not available; skipping poll"
  exit 0
fi

log "publication log poll starting"
uv run git-legislation poll-publication-log 2>&1 | tail -8

log "extracting legal dates"
uv run git-legislation extract-legal-dates 2>&1 | tail -2

log "copying content objects to R2 (additive; prune-r2.sh handles deletions)"
zsh scripts/sync.sh 2>&1 | tail -1

log "delta-syncing rows to PlanetScale"
zsh scripts/delta-sync-planetscale.sh "$(date -v-3d '+%Y-%m-%d')" 2>&1 | tail -2

log "POLL COMPLETE"
