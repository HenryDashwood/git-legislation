-- +goose Up
-- Amendment effects from legislation.gov.uk's Changes to Legislation database:
-- the editorial record of which instrument changed which provision, and when it
-- came into force. Document ids are plain text, not foreign keys: effects
-- legitimately reference legislation that is not published on the site (the
-- "not available" rows in their UI), and those dangling edges are worth keeping.
create table effects (
    id text primary key,
    uri text,
    effect_type text not null,
    textual_kind text,
    applied boolean not null default false,
    requires_applied boolean not null default false,
    prospective boolean not null default false,
    in_force_date date,
    in_force_qualification text,
    commencing_document_id text,
    commencement_authority text,
    affected_document_id text,
    affected_title text,
    affected_provisions text,
    affecting_document_id text,
    affecting_title text,
    affecting_provisions text,
    comments text,
    modified timestamp with time zone,
    created_at timestamp with time zone not null default now(),
    updated_at timestamp with time zone not null default now()
);

create index effects_affected_idx on effects (affected_document_id, in_force_date);
create index effects_affecting_idx on effects (affecting_document_id, in_force_date);
create index effects_modified_idx on effects (modified);

-- Per-provision references on each side of an effect. section_number is the
-- top-level provision number parsed out of the structural ref
-- ("section-28D-4" -> "28D"), which is what joins to provisions.number.
create table effect_provisions (
    id bigserial primary key,
    effect_id text not null references effects(id) on delete cascade,
    side text not null check (side in ('affected', 'affecting', 'commencing')),
    provision_kind text,
    section_number text,
    ref text,
    uri text,
    label text
);

create index effect_provisions_effect_idx on effect_provisions (effect_id, side);
create index effect_provisions_lookup_idx on effect_provisions (side, section_number);

-- Poll watermark per affected document, mirroring publication_log_cursor:
-- their feed exposes a Modified timestamp per effect, so refreshes are incremental.
create table effects_cursor (
    document_id text primary key,
    last_modified timestamp with time zone,
    effect_count integer not null default 0,
    refreshed_at timestamp with time zone not null default now()
);

-- +goose Down
drop table effects_cursor;
drop table effect_provisions;
drop table effects;
