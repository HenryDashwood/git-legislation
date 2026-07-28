#!/bin/zsh
# One-shot data load: local Postgres -> PlanetScale, using the docker
# container's PG18 client tools. Requires only INSERT/UPDATE on the target
# (pg_write_all_data): the circular documents.latest_version_id reference is
# loaded as NULL first and backfilled with an UPDATE once document_versions
# exists, so no ALTER TABLE is needed.
set -euo pipefail
export PATH="$HOME/.docker/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"
cd /Users/henrydashwood/git-legislation

# The PlanetScale DSN is whichever DB_URL line in .envrc points at psdb.cloud,
# commented or not; the local docker database is always the copy source.
PSCALE_URL="${PSCALE_URL:-$(grep -o 'postgres[^"]*psdb\.cloud[^"]*' .envrc | head -1 || true)}"
if [[ -z "$PSCALE_URL" ]]; then
  print -r -- "PSCALE_URL is not set and no psdb.cloud DSN found in .envrc" >&2
  exit 1
fi

CONTAINER=git-legislation-postgres-1
LOCAL_DB=british_legislation

log() { print -r -- "[$(date '+%F %T')] $*"; }

psql_local() {
  docker exec -i "$CONTAINER" psql -U postgres -d "$LOCAL_DB" -v ON_ERROR_STOP=1 "$@"
}

psql_target() {
  docker exec -i "$CONTAINER" psql "$PSCALE_URL" -v ON_ERROR_STOP=1 "$@"
}

# Order matters: parents before children, so foreign keys resolve as we go.
# The effects tables reference documents only by plain text (an effect can name
# legislation that is not published), so they can load last without constraints.
TABLES=(
  storage_objects documents document_versions provision_texts provisions document_files
  fetch_runs fetch_observations effects effect_provisions effects_cursor
)

log "checking target is empty"
for table in "${TABLES[@]}"; do
  count=$(psql_target -t -A -c "select count(*) from $table")
  if [[ "$count" != "0" ]]; then
    log "ABORT: target table $table already has $count rows"
    exit 1
  fi
done

for table in "${TABLES[@]}"; do
  log "loading $table"
  if [[ "$table" == "documents" ]]; then
    cols=$(psql_local -t -A -c "select string_agg(column_name, ',' order by ordinal_position) from information_schema.columns where table_schema='public' and table_name='documents' and column_name <> 'latest_version_id'")
    psql_local -c "\\copy (select $cols from documents) to stdout" \
      | psql_target -c "\\copy documents($cols) from stdin"
  else
    psql_local -c "\\copy $table to stdout" \
      | psql_target -c "\\copy $table from stdin"
  fi
  count=$(psql_target -t -A -c "select count(*) from $table")
  log "$table loaded: $count rows"
done

# COPY writes explicit ids without advancing the owning sequence, so any later
# insert on the target would collide until the sequences are moved past the
# loaded maximum.
log "resetting id sequences"
psql_target -q -c "
do \$\$
declare rec record;
begin
  for rec in
    select c.table_name, c.column_name,
           pg_get_serial_sequence(c.table_name, c.column_name) as seq
    from information_schema.columns c
    where c.table_schema = 'public'
      and pg_get_serial_sequence(c.table_name, c.column_name) is not null
  loop
    execute format('select setval(%L, coalesce((select max(%I) from %I), 0) + 1, false)',
                   rec.seq, rec.column_name, rec.table_name);
  end loop;
end \$\$;"

log "backfilling documents.latest_version_id"
{
  print -r -- "create temp table _doc_latest(id text primary key, latest_version_id text);"
  print -r -- "\\copy _doc_latest from stdin"
  docker exec "$CONTAINER" psql -U postgres -d "$LOCAL_DB" -t -c "\\copy (select id, latest_version_id from documents where latest_version_id is not null) to stdout"
  print -r -- "\\."
  print -r -- "update documents d set latest_version_id = t.latest_version_id from _doc_latest t where d.id = t.id;"
} | psql_target -q
backfilled=$(psql_target -t -A -c "select count(*) from documents where latest_version_id is not null")
log "latest_version_id backfilled on $backfilled documents"

log "analyzing (best effort)"
psql_target -c "analyze;" || log "analyze not permitted for this role; skipping"

log "PLANETSCALE LOAD COMPLETE"
