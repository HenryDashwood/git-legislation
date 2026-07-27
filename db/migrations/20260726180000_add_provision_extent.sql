-- +goose Up
-- Where an Act's text diverges by jurisdiction, CLML holds the alternative
-- readings in a Versions container tagged with an extent. Those are now
-- rendered as their own provisions, so a provision is identified by
-- (document, version, number, extent) rather than number alone.
alter table provisions add column extent text;
create index provisions_document_number_extent_idx on provisions (document_id, number, extent);

-- +goose Down
drop index provisions_document_number_extent_idx;
alter table provisions drop column extent;
