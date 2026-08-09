-- +goose Up
-- Landing tables for the LLM enrichment of powers (scripts/enrich-powers.py):
-- one enrichment row per power, one row per extracted target with its
-- resolution against the orgs entity dictionary, and one row per typed
-- constraint on the power's exercise. Kept apart from duties.duties because
-- enrichment is regenerable model output with its own provenance, while
-- duties mirrors the published dataset.
create table duties.power_enrichments (
    duty_id bigint primary key references duties.duties (id) on delete cascade,
    instrument text not null check (
        instrument in ('legislate', 'direct', 'guide', 'appoint', 'establish', 'fund', 'authorise',
                       'charge', 'inspect', 'enforce', 'adjudicate', 'acquire', 'other')
    ),
    is_direction_power boolean not null,
    -- For instrument = 'legislate' only: the parliamentary procedure the
    -- instrument is subject to. Not extractable from the action text alone -
    -- populated by a later pass over the parent provision's full text, where
    -- the "subject to annulment" / "approved by a resolution" formulae live.
    si_procedure text check (
        si_procedure in ('affirmative', 'negative', 'laid_only', 'no_procedure', 'unknown')
    ),
    model text not null,
    enriched_at timestamp with time zone not null default now()
);

create index power_enrichments_instrument_idx on duties.power_enrichments (instrument);
create index power_enrichments_direction_idx on duties.power_enrichments (duty_id)
    where is_direction_power;

create table duties.power_targets (
    id bigint generated always as identity primary key,
    duty_id bigint not null references duties.duties (id) on delete cascade,
    target_text text not null,
    -- exact: target_text equals an entity name; alias: equals a recorded
    -- alias; unresolved: no dictionary hit yet (a later, reviewed pass may
    -- upgrade these - see the llm-link precision warning in scripts/).
    entity_id bigint references orgs.entities (id),
    resolution text not null default 'unresolved'
        check (resolution in ('exact', 'alias', 'unresolved'))
);

create unique index power_targets_unique_idx on duties.power_targets (duty_id, lower(target_text));
create index power_targets_entity_idx on duties.power_targets (entity_id) where entity_id is not null;

-- Typed limits on the exercise of a power - "must consult X first", "capped
-- at £y", "within z days", "must have due regard to ...". The raw material is
-- mostly already in duties.duties.condition (populated on ~71% of rows);
-- constraint_type is assigned by a classification pass over that text, with
-- provision-text passes able to add rows the condition field missed.
create table duties.power_constraints (
    id bigint generated always as identity primary key,
    duty_id bigint not null references duties.duties (id) on delete cascade,
    constraint_type text not null check (
        constraint_type in ('consultation', 'consent', 'due_regard', 'time_limit', 'financial_cap',
                            'procedural', 'precondition', 'other')
    ),
    constraint_text text not null,
    source text not null
);

create index power_constraints_duty_idx on duties.power_constraints (duty_id);
create index power_constraints_type_idx on duties.power_constraints (constraint_type);

-- +goose Down
drop table duties.power_constraints;
drop table duties.power_targets;
drop table duties.power_enrichments;
