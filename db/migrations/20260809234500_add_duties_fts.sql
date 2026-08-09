-- +goose Up
-- Full-text search over what a power lets the actor do - the literal half of
-- task-first retrieval ("what powers are available to do xyz"); embeddings
-- are the other half and live with the serving-layer decision. Separate
-- migration because the stored column rewrites the 1.7 GB duties table and
-- the GIN build takes minutes: run it when nothing is holding locks on
-- duties.duties.
alter table duties.duties
    add column action_tsv tsvector
    generated always as (to_tsvector('english', action || ' ' || coalesce(condition, ''))) stored;

create index duties_action_tsv_idx on duties.duties using gin (action_tsv);

-- +goose Down
alter table duties.duties drop column action_tsv;
