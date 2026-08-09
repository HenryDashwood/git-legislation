-- +goose Up
-- Entity dictionary: government bodies, offices, and generic legal classes,
-- with the aliases needed to resolve the names legislation actually uses
-- ("Office of Communications" -> Ofcom, "Independent System Operator and
-- Planner" -> NESO). Seeded from the GOV.UK organisations register (which
-- includes closed bodies, closure reasons, and successor links), enriched
-- from machineryofgovernment.uk, and linked to the actor vocabulary in the
-- duties schema. Its own schema because it will serve more than duties.
create schema orgs;

create table orgs.entities (
    id bigint generated always as identity primary key,
    name text not null,
    -- body: an organisation; office: an officeholder (Secretary of State,
    -- Lord Chancellor); class: a generic legal category that legislation
    -- addresses ("local authority", "constable") - never a real organisation.
    kind text not null check (kind in ('body', 'office', 'class')),
    org_type text,
    status text,
    closed_reason text,
    closed_at date,
    govuk_slug text unique,
    mog_id text unique,
    legislation_uri text unique,
    parent_id bigint references orgs.entities (id),
    successor_id bigint references orgs.entities (id),
    created_at timestamp with time zone not null default now()
);

create index entities_name_idx on orgs.entities (lower(name));
create index entities_kind_idx on orgs.entities (kind, status);

-- Aliases are observed strings only - an official abbreviation, a former name
-- along a changed_name chain, a statutory designation, or an actor string
-- from the duties data that an LLM linked to the entity. source records where
-- each one was observed so nothing is ever invented silently.
create table orgs.entity_aliases (
    entity_id bigint not null references orgs.entities (id) on delete cascade,
    alias text not null,
    alias_kind text not null check (
        alias_kind in ('abbreviation', 'former_name', 'statutory_name', 'actor_name', 'display_name')
    ),
    source text not null
);

create unique index entity_aliases_unique_idx on orgs.entity_aliases (entity_id, lower(alias));
create index entity_aliases_alias_idx on orgs.entity_aliases (lower(alias));

-- Membership of generic classes ("NESO is an electricity system operator
-- licence holder") - what lets a class-addressed power resolve to concrete
-- bodies. Curated knowledge, populated sparsely as needed.
create table orgs.entity_class_members (
    entity_id bigint not null references orgs.entities (id) on delete cascade,
    class_id bigint not null references orgs.entities (id) on delete cascade,
    source text not null,
    primary key (entity_id, class_id)
);

-- +goose Down
drop schema orgs cascade;
