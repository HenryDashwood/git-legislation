-- +goose Up
-- Target matching in the powers search is a substring test ("licence holder"
-- has to match "the holder of an electricity system operator licence"), which
-- no btree can serve: the CTE scanned all 436k power_targets rows and took
-- 23.5s. Trigram indexes make ILIKE '%...%' indexable and bring it under a
-- second.
create extension if not exists pg_trgm;

create index power_targets_text_trgm_idx
    on duties.power_targets using gin (target_text gin_trgm_ops);

create index entities_name_trgm_idx
    on orgs.entities using gin (name gin_trgm_ops);

-- The scoring query filters powers by modality and actor before ranking;
-- without this the planner reaches for a sequential scan on the 1.7 GB table.
create index duties_modality_actor_idx
    on duties.duties (modality)
    where modality in ('power', 'both');

-- +goose Down
drop index if exists duties.duties_modality_actor_idx;
drop index if exists orgs.entities_name_trgm_idx;
drop index if exists duties.power_targets_text_trgm_idx;
