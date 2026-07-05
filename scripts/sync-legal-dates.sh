#!/bin/zsh
# Copy documents.legal_date/legal_date_kind values from local Postgres to
# PlanetScale. Requires the columns to exist on the target (goose migration
# 20260705140355, which needs a table-owner role to apply); the value sync
# itself only needs pg_write_all_data.
set -euo pipefail
export PATH="$HOME/.docker/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"
cd /Users/henrydashwood/git-legislation

PSCALE_URL="${PSCALE_URL:-$(grep -o 'postgres[^"]*psdb\.cloud[^"]*' .envrc | head -1)}"
CONTAINER=git-legislation-postgres-1

log() { print -r -- "[$(date '+%F %T')] $*"; }

log "streaming legal dates to PlanetScale"
{
  print -r -- "create temp table _dates(id text primary key, legal_date date, legal_date_kind text);"
  print -r -- "\\copy _dates from stdin"
  docker exec "$CONTAINER" psql -U postgres -d british_legislation -c \
    "\\copy (select id, legal_date, legal_date_kind from documents where legal_date is not null) to stdout"
  print -r -- "\\."
  print -r -- "update documents d set legal_date = t.legal_date, legal_date_kind = t.legal_date_kind from _dates t where d.id = t.id;"
  print -r -- "select count(*) as dated from documents where legal_date is not null;"
} | docker exec -i "$CONTAINER" psql "$PSCALE_URL" -v ON_ERROR_STOP=1
log "LEGAL DATE SYNC COMPLETE"
