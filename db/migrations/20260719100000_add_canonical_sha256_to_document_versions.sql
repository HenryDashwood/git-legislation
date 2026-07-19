-- +goose Up
alter table document_versions add column canonical_sha256 text;
create index document_versions_canonical_content_idx
    on document_versions (document_id, version_kind, canonical_sha256);

-- +goose Down
drop index document_versions_canonical_content_idx;
alter table document_versions drop column canonical_sha256;
