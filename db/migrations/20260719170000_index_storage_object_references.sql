-- +goose Up
-- FK columns referencing storage_objects(key) were unindexed, so any
-- delete/update on storage_objects sequential-scans the referencing tables
-- per row (discovered when a bulk cleanup on the serving copy ran for over
-- an hour without finishing).
create index document_versions_source_object_key_idx
    on document_versions (source_object_key);
create index document_versions_markdown_object_key_idx
    on document_versions (markdown_object_key);
create index document_files_object_key_idx
    on document_files (object_key);

-- +goose Down
drop index document_files_object_key_idx;
drop index document_versions_markdown_object_key_idx;
drop index document_versions_source_object_key_idx;
