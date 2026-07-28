#!/bin/zsh
# Incremental row sync: local Postgres -> PlanetScale. Idempotent upserts via
# temp tables; safe to re-run with any --since window. Handles the circular
# documents<->document_versions FK by deferring latest_version_id, and heals
# document_files.object_key backfills (the sweep sets object_key on rows
# created long before, which a created_at watermark alone would miss).
#
# Usage: delta-sync-planetscale.sh [SINCE]   (default: 14 days ago)
set -euo pipefail
export PATH="$HOME/.docker/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"
cd /Users/henrydashwood/git-legislation

SINCE="${1:-$(date -v-14d '+%Y-%m-%d')}"
PSCALE_URL="${PSCALE_URL:-$(grep -o 'postgres[^"]*psdb\.cloud[^"]*' .envrc | head -1)}"
CONTAINER=git-legislation-postgres-1
LOCAL_DB=british_legislation
WORK_DIR=$(mktemp -d /tmp/delta-sync.XXXXXX)
trap "rm -rf $WORK_DIR" EXIT

log() { print -r -- "[$(date '+%F %T')] $*"; }

dump_local() {
  docker exec "$CONTAINER" psql -U postgres -d "$LOCAL_DB" -v ON_ERROR_STOP=1 \
    -c "\\copy ($1) to stdout" > "$2"
}

sync_table() {
  local name=$1 select=$2 ddl=$3 upsert=$4
  dump_local "$select" "$WORK_DIR/$name.tsv"
  local rows=$(wc -l < "$WORK_DIR/$name.tsv" | tr -d ' ')
  {
    print -r -- "$ddl"
    print -r -- "\\copy _stage from stdin"
    cat "$WORK_DIR/$name.tsv"
    print -r -- "\\."
    print -r -- "$upsert"
  } | docker exec -i "$CONTAINER" psql "$PSCALE_URL" -v ON_ERROR_STOP=1 -q
  log "$name: staged $rows rows"
}

log "delta sync since $SINCE"

sync_table storage_objects \
  "select * from storage_objects where created_at >= '$SINCE'" \
  "create temp table _stage (like storage_objects including defaults);" \
  "insert into storage_objects select * from _stage
   on conflict (key) do update set sha256 = excluded.sha256, byte_size = excluded.byte_size,
     content_type = excluded.content_type, source_url = excluded.source_url;"

sync_table documents \
  "select * from documents where updated_at >= '$SINCE'" \
  "create temp table _stage (like documents including defaults);" \
  "insert into documents (id, legislation_type, year, calendar_year, number, title, document_uri,
     status, extent, source_path, created_at, updated_at, legal_date, legal_date_kind)
   select id, legislation_type, year, calendar_year, number, title, document_uri,
     status, extent, source_path, created_at, updated_at, legal_date, legal_date_kind
   from _stage
   on conflict (id) do update set
     title = excluded.title, document_uri = excluded.document_uri, status = excluded.status,
     extent = excluded.extent, source_path = excluded.source_path, updated_at = excluded.updated_at,
     legal_date = excluded.legal_date, legal_date_kind = excluded.legal_date_kind;"

sync_table document_versions \
  "select * from document_versions where created_at >= '$SINCE'" \
  "create temp table _stage (like document_versions including defaults);" \
  "insert into document_versions select * from _stage
   on conflict (id) do update set
     source_uri = excluded.source_uri, source_object_key = excluded.source_object_key,
     markdown_object_key = excluded.markdown_object_key, source_sha256 = excluded.source_sha256,
     markdown_sha256 = excluded.markdown_sha256, word_count = excluded.word_count,
     is_metadata_only = excluded.is_metadata_only;"

# Deferred circular pointer, now that both sides exist on the target.
sync_table documents_latest_pointer \
  "select id, latest_version_id from documents where updated_at >= '$SINCE' and latest_version_id is not null" \
  "create temp table _stage (id text primary key, latest_version_id text);" \
  "update documents d set latest_version_id = t.latest_version_id
   from _stage t where d.id = t.id and t.latest_version_id is distinct from d.latest_version_id;"

# Provision text is content-addressed, so the shared texts must land before the
# rows that reference them. Only texts newly referenced in this window are sent.
sync_table provision_texts \
  "select t.* from provision_texts t where exists (
     select 1 from provisions p where p.text_sha256 = t.sha256 and p.created_at >= '$SINCE')" \
  "create temp table _stage (like provision_texts including defaults);" \
  "insert into provision_texts select * from _stage on conflict (sha256) do nothing;"

sync_table provisions \
  "select * from provisions where created_at >= '$SINCE'" \
  "create temp table _stage (like provisions including defaults);" \
  "insert into provisions select * from _stage
   on conflict (id) do update set
     provision_type = excluded.provision_type, number = excluded.number, heading = excluded.heading,
     anchor = excluded.anchor, text_sha256 = excluded.text_sha256, extent = excluded.extent;"

sync_table document_files \
  "select * from document_files where created_at >= '$SINCE'" \
  "create temp table _stage (like document_files including defaults);" \
  "insert into document_files select * from _stage on conflict (id) do nothing;"

sync_table document_files_object_keys \
  "select id, object_key, sha256 from document_files where object_key is not null" \
  "create temp table _stage (id bigint primary key, object_key text, sha256 text);" \
  "update document_files df set object_key = t.object_key, sha256 = t.sha256
   from _stage t where df.id = t.id and df.object_key is null;"

sync_table fetch_runs \
  "select * from fetch_runs where started_at >= '$SINCE'" \
  "create temp table _stage (like fetch_runs including defaults);" \
  "insert into fetch_runs select * from _stage
   on conflict (id) do update set finished_at = excluded.finished_at, notes = excluded.notes;"

sync_table fetch_observations \
  "select * from fetch_observations where observed_at >= '$SINCE'" \
  "create temp table _stage (like fetch_observations including defaults);" \
  "insert into fetch_observations select * from _stage on conflict (id) do nothing;"

log "DELTA SYNC COMPLETE"
