-- +goose Up
create table publication_log_cursor (
    id integer primary key check (id = 1),
    last_polled_date date not null,
    updated_at timestamp with time zone not null default now()
);

-- +goose Down
drop table publication_log_cursor;
