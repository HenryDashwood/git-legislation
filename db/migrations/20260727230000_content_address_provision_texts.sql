-- +goose Up
-- Provision text was stored inline on every provision row, so each version of a
-- document repeated the full text of every provision whether or not it changed:
-- Town and Country Planning Act 1990 held 135,880 rows carrying 2,238 distinct
-- texts. Store each distinct text once, keyed by its hash, and let provisions
-- reference it. Version identity is already content-addressed
-- (document_versions.canonical_sha256); this is the same idea one level down.
create table provision_texts (
    sha256 text primary key,
    markdown text not null,
    plain_text text not null,
    created_at timestamp with time zone not null default now()
);

insert into provision_texts (sha256, markdown, plain_text)
select distinct on (encode(sha256(convert_to(markdown, 'UTF8')), 'hex'))
       encode(sha256(convert_to(markdown, 'UTF8')), 'hex'), markdown, plain_text
from provisions;

alter table provisions add column text_sha256 text;

update provisions
set text_sha256 = encode(sha256(convert_to(markdown, 'UTF8')), 'hex');

alter table provisions alter column text_sha256 set not null;
alter table provisions
    add constraint provisions_text_sha256_fkey foreign key (text_sha256) references provision_texts(sha256);
create index provisions_text_idx on provisions (text_sha256);

alter table provisions drop column markdown;
alter table provisions drop column plain_text;

-- +goose Down
alter table provisions add column markdown text;
alter table provisions add column plain_text text;

update provisions p
set markdown = t.markdown, plain_text = t.plain_text
from provision_texts t
where t.sha256 = p.text_sha256;

alter table provisions alter column markdown set not null;
alter table provisions alter column plain_text set not null;
alter table provisions drop column text_sha256;
drop table provision_texts;
