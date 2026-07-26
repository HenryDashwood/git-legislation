#!/bin/zsh
# Push a converter re-render plus the effects tables to the serving database.
#
# The daily delta-sync cannot carry this: rerender-document-versions updates
# document_versions rows in place (old created_at, so a watermark misses them)
# and deletes/reinserts provisions (deletes never propagate through upserts).
# This replaces the affected documents' provisions wholesale and copies the
# effects tables, without touching the rest of the corpus.
#
# Usage: sync-pilot-rerender.sh [PATH_FILE]   (default: scripts/pilot-acts.txt)
set -euo pipefail
export PATH="$HOME/.docker/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"
cd /Users/henrydashwood/git-legislation

PATH_FILE="${1:-scripts/pilot-acts.txt}"
PSCALE_URL="${PSCALE_URL:-$(grep -o 'postgres[^"]*psdb\.cloud[^"]*' .envrc | head -1)}"
CONTAINER=git-legislation-postgres-1
LOCAL_DB=british_legislation

log() { print -r -- "[$(date '+%F %T')] $*"; }
psql_local() { docker exec -i "$CONTAINER" psql -U postgres -d "$LOCAL_DB" -v ON_ERROR_STOP=1 "$@"; }
psql_target() { docker exec -i "$CONTAINER" psql "$PSCALE_URL" -v ON_ERROR_STOP=1 "$@"; }

# Document ids, quoted for a SQL in-list.
DOC_IDS=$(sed 's/#.*//' "$PATH_FILE" | tr -d ' \t' | grep -v '^$' | sed "s/.*/'&'/" | paste -sd, -)
if [[ -z "$DOC_IDS" ]]; then
  log "ABORT: no document ids in $PATH_FILE"
  exit 1
fi
log "syncing $(print -r -- "$DOC_IDS" | tr ',' '\n' | wc -l | tr -d ' ') documents"

log "refreshing storage_objects for re-rendered Markdown"
{
  print -r -- "create temp table _so (like storage_objects including defaults);"
  print -r -- "\\copy _so from stdin"
  psql_local -t -c "\\copy (select so.* from storage_objects so join document_versions dv
      on dv.markdown_object_key = so.key where dv.document_id in ($DOC_IDS)) to stdout"
  print -r -- "\\."
  print -r -- "insert into storage_objects select * from _so
      on conflict (key) do update set sha256 = excluded.sha256, byte_size = excluded.byte_size,
        content_type = excluded.content_type;"
} | psql_target -q

log "refreshing document_versions hashes and word counts"
{
  print -r -- "create temp table _dv (like document_versions including defaults);"
  print -r -- "\\copy _dv from stdin"
  psql_local -t -c "\\copy (select * from document_versions where document_id in ($DOC_IDS)) to stdout"
  print -r -- "\\."
  print -r -- "insert into document_versions select * from _dv
      on conflict (id) do update set
        markdown_sha256 = excluded.markdown_sha256,
        canonical_sha256 = excluded.canonical_sha256,
        word_count = excluded.word_count,
        is_metadata_only = excluded.is_metadata_only;"
} | psql_target -q

log "replacing provisions for those documents"
{
  print -r -- "create temp table _p (like provisions including defaults);"
  print -r -- "\\copy _p from stdin"
  psql_local -t -c "\\copy (select * from provisions where document_id in ($DOC_IDS)) to stdout"
  print -r -- "\\."
  print -r -- "begin;"
  print -r -- "delete from provisions where document_id in ($DOC_IDS);"
  print -r -- "insert into provisions select * from _p;"
  print -r -- "commit;"
} | psql_target -q
log "provisions now: $(psql_target -t -A -c "select count(*) from provisions where document_id in ($DOC_IDS)")"

log "refreshing document_files hashes"
{
  print -r -- "create temp table _df (like document_files including defaults);"
  print -r -- "\\copy _df from stdin"
  psql_local -t -c "\\copy (select * from document_files where document_id in ($DOC_IDS)) to stdout"
  print -r -- "\\."
  print -r -- "update document_files df set sha256 = s.sha256 from _df s where s.id = df.id;"
} | psql_target -q

for table in effects effect_provisions effects_cursor; do
  log "copying $table"
  {
    print -r -- "create temp table _t (like $table including defaults);"
    print -r -- "\\copy _t from stdin"
    psql_local -t -c "\\copy $table to stdout"
    print -r -- "\\."
    print -r -- "begin;"
    print -r -- "delete from $table;"
    print -r -- "insert into $table select * from _t;"
    print -r -- "commit;"
  } | psql_target -q
  log "$table now: $(psql_target -t -A -c "select count(*) from $table")"
done

log "schedule provisions on target: $(psql_target -t -A -c "select count(*) from provisions where provision_type='schedule'")"
log "PILOT RERENDER SYNC COMPLETE"
