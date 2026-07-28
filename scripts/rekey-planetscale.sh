#!/bin/zsh
# Step 2 of the compression cutover: point the serving database at the gzipped
# object keys.
#
# Only the keys changed, so this rewrites them in place rather than reloading
# 2.6M provisions. storage_objects.key is referenced by document_versions
# (twice) and document_files, so the new rows are inserted, the references
# moved, and the old rows dropped — all inside one transaction, so the database
# is never half-way between the two key sets.
#
# Run only after copy-compressed-to-r2.sh has finished AND the read-api that
# decompresses .gz has been deployed: the bucket must already hold these keys,
# and the worker must know how to serve them.
set -euo pipefail
export PATH="$HOME/.docker/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"
cd /Users/henrydashwood/git-legislation

PSCALE_URL="${PSCALE_URL:-$(grep -o 'postgres[^"]*psdb\.cloud[^"]*' .envrc | head -1)}"
CONTAINER=git-legislation-postgres-1
log() { print -r -- "[$(date '+%F %T')] $*"; }
psql_target() { docker exec -i "$CONTAINER" psql "$PSCALE_URL" -v ON_ERROR_STOP=1 "$@"; }

before=$(psql_target -t -A -c "select count(*) from storage_objects where key like '%.gz'")
log "compressed keys on target before: $before"

log "rewriting keys for compressible objects"
psql_target -q <<'SQL'
begin;

create temp table _rekey as
select key as old_key, key || '.gz' as new_key
from storage_objects
where key not like '%.gz'
  and (
    content_type like 'text/%'
    or content_type in ('application/xml', 'application/json', 'application/x-ndjson')
  );

insert into storage_objects (key, bucket, sha256, byte_size, content_type, source_url)
select r.new_key, s.bucket, s.sha256, s.byte_size, s.content_type, s.source_url
from _rekey r join storage_objects s on s.key = r.old_key
on conflict (key) do nothing;

update document_versions v set source_object_key = r.new_key
from _rekey r where v.source_object_key = r.old_key;

update document_versions v set markdown_object_key = r.new_key
from _rekey r where v.markdown_object_key = r.old_key;

update document_files f set object_key = r.new_key
from _rekey r where f.object_key = r.old_key;

delete from storage_objects s using _rekey r where s.key = r.old_key;

commit;
SQL

after=$(psql_target -t -A -c "select count(*) from storage_objects where key like '%.gz'")
stale=$(psql_target -t -A -c "
  select count(*) from document_files f
  where f.object_key is not null
    and not exists (select 1 from storage_objects s where s.key = f.object_key)")
log "compressed keys on target after: $after (stale file links: $stale)"
log "REKEY COMPLETE"
