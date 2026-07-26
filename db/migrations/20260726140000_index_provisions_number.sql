-- +goose Up
-- Effects name affected provisions by number ("s. 28D" -> provisions.number
-- '28D'), so resolving an effect to local text joins on (document_id, number).
-- Without this index that join sequential-scans a 2.2M-row table per lookup.
create index provisions_document_number_idx on provisions (document_id, number);

-- +goose Down
drop index provisions_document_number_idx;
