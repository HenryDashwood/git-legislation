-- +goose Up
-- Statutory Powers & Duties dataset from research.legislation.gov.uk: one row
-- per power or duty that the National Archives extracted from in-force
-- legislation with an LLM (Claude Sonnet 4.5). Research-grade, not
-- authoritative: the publisher warns of errors and omissions, so this lives in
-- its own schema as an overlay rather than alongside the canonical tables.
create schema duties;

-- The CSVs repeat a whole row for every recognised body an actor resolves to
-- (only actorIsAlias/body_uri differ between repeats), so the release is
-- denormalized: rows collapse to one duty here, and the body matches move to
-- duty_actor_matches.
create table duties.duties (
    id bigint generated always as identity primary key,
    -- duty_uri embeds the per-document extraction date, so each dataset
    -- release mints fresh URIs; uniqueness holds within a release, and
    -- dataset_date keeps releases distinguishable if loaded side by side.
    duty_uri text not null unique,
    source_temp_id bigint,
    enactment_uri text not null,
    -- Matches documents.id (the URI tail after /id/, regnal segments and all)
    -- but stays plain text like effects: EU legislation (eur/eudn/eudr,
    -- ~185k rows) is in this dataset yet not ingested here, so those rows
    -- keep a null document_id and rely on the denormalized enactment columns.
    document_id text,
    -- Derived from enactment_uri, not the CSV's enactmentType column, which
    -- mixes short codes with spelled-out labels ("ScottishAct" for asp).
    enactment_type text not null,
    enactment_title text not null,
    enactment_year text,
    enactment_number text,
    section_uri text not null,
    -- section_uri relative to the enactment: 'section/2', 'schedule/2/paragraph/5'.
    section_path text not null,
    provision_kind text,
    -- Top-level provision number ('2', '28D') when the path is simple enough
    -- to name one; joins to provisions.number the same way
    -- effect_provisions.section_number does.
    provision_number text,
    subsections text[],
    actor text not null,
    actor_definition text,
    modality text not null check (modality in ('power', 'duty', 'both', 'unknown')),
    action text not null,
    condition text,
    inference text check (inference in ('explicit', 'implicit')),
    priority text check (priority in ('primary', 'secondary')),
    dataset_date date not null,
    source_file text not null,
    created_at timestamp with time zone not null default now()
);

create index duties_document_idx on duties.duties (document_id);
create index duties_provision_idx on duties.duties (document_id, provision_number);
create index duties_modality_idx on duties.duties (modality);
create index duties_actor_idx on duties.duties (actor);

-- One row per (duty, recognised body) pairing. direct = the CSV's actorIsBody
-- (actor named a body outright); alias = actorIsAlias (matched through a
-- statutory definition). body_uri is the /id/organisation/... identifier,
-- populated for ~2% of matches.
create table duties.duty_actor_matches (
    duty_id bigint not null references duties.duties (id) on delete cascade,
    body_name text not null,
    match_kind text not null check (match_kind in ('direct', 'alias')),
    body_uri text,
    primary key (duty_id, body_name, match_kind)
);

create index duty_actor_matches_body_idx on duties.duty_actor_matches (body_name);
create index duty_actor_matches_uri_idx on duties.duty_actor_matches (body_uri)
    where body_uri is not null;

-- +goose Down
drop schema duties cascade;
