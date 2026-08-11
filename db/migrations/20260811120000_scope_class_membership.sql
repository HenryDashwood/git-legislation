-- +goose Up
-- Class membership must be scoped to the enactment that defines the class.
-- Unscoped membership is not merely imprecise, it is wrong: "licence holder"
-- names a different set in every Act, so an unscoped claim that NESO is a
-- licence holder reached Animals (Scientific Procedures) Act and Chemical
-- Weapons Act licensees (~1,489 false powers when tested on 2026-08-11).
-- Scoped, the same claim reads "NESO is a licence holder for the purposes of
-- the Electricity Act 1989", which is both true and useful: every
-- licence-holder power in that Act genuinely applies to NESO.
--
-- document_id is required. It is plain text rather than a foreign key, for
-- the same reason as effects.affected_document_id: a class may be defined by
-- an enactment that is not in the corpus.
delete from orgs.entity_class_members;

alter table orgs.entity_class_members
    add column document_id text not null;

alter table orgs.entity_class_members
    drop constraint entity_class_members_pkey;

alter table orgs.entity_class_members
    add primary key (entity_id, class_id, document_id);

create index entity_class_members_class_idx on orgs.entity_class_members (class_id, document_id);

-- +goose Down
delete from orgs.entity_class_members;

alter table orgs.entity_class_members drop constraint entity_class_members_pkey;
drop index if exists orgs.entity_class_members_class_idx;
alter table orgs.entity_class_members drop column document_id;
alter table orgs.entity_class_members add primary key (entity_id, class_id);
