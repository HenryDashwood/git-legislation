-- +goose Up
alter table documents add column legal_date date;
alter table documents add column legal_date_kind text
    check (legal_date_kind in ('made', 'enacted'));

-- +goose Down
alter table documents drop column legal_date_kind;
alter table documents drop column legal_date;
