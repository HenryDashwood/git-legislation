-- +goose Up
-- +goose StatementBegin
CREATE TABLE storage_objects (
    key TEXT PRIMARY KEY,
    bucket TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size BIGINT NOT NULL CHECK (byte_size >= 0),
    content_type TEXT,
    source_url TEXT,
    fetched_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    legislation_type TEXT NOT NULL,
    YEAR TEXT NOT NULL,
    calendar_year INTEGER,
    number TEXT NOT NULL,
    title TEXT NOT NULL,
    document_uri TEXT NOT NULL,
    status TEXT,
    extent TEXT,
    source_path TEXT[] NOT NULL,
    latest_version_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE document_versions (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    version_kind TEXT NOT NULL CHECK (
        version_kind IN ('enacted', 'point_in_time', 'current')
    ),
    snapshot_date date,
    source_uri TEXT,
    source_object_key TEXT REFERENCES storage_objects (key),
    markdown_object_key TEXT REFERENCES storage_objects (key),
    source_sha256 TEXT NOT NULL,
    markdown_sha256 TEXT,
    word_count INTEGER NOT NULL DEFAULT 0 CHECK (word_count >= 0),
    is_metadata_only BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
        (
            version_kind = 'point_in_time'
            AND snapshot_date IS NOT NULL
        )
        OR (
            version_kind IN ('enacted', 'current')
            AND snapshot_date IS NULL
        )
    )
);

ALTER TABLE documents
ADD CONSTRAINT documents_latest_version_id_fkey FOREIGN key (latest_version_id) REFERENCES document_versions (id) ON DELETE SET NULL;

CREATE TABLE document_files (
    id bigserial PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    version_id TEXT REFERENCES document_versions (id) ON DELETE CASCADE,
    file_kind TEXT NOT NULL CHECK (
        file_kind IN (
            'clml_xml',
            'pdf',
            'markdown',
            'extracted_text',
            'report',
            'other'
        )
    ),
    source_url TEXT,
    object_key TEXT REFERENCES storage_objects (key),
    sha256 TEXT,
    is_canonical BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE provisions (
    id TEXT PRIMARY KEY,
    version_id TEXT NOT NULL REFERENCES document_versions (id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    provision_type TEXT,
    number TEXT,
    heading TEXT NOT NULL,
    anchor TEXT NOT NULL,
    markdown TEXT NOT NULL,
    plain_text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (version_id, ordinal)
);

CREATE TABLE fetch_runs (
    id bigserial PRIMARY KEY,
    mode TEXT NOT NULL CHECK (
        mode IN (
            'enacted',
            'point_in_time',
            'current',
            'publication_log',
            'other'
        )
    ),
    snapshot_date date,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    notes TEXT
);

CREATE TABLE fetch_observations (
    id bigserial PRIMARY KEY,
    fetch_run_id BIGINT REFERENCES fetch_runs (id) ON DELETE SET NULL,
    document_id TEXT REFERENCES documents (id) ON DELETE SET NULL,
    version_id TEXT REFERENCES document_versions (id) ON DELETE SET NULL,
    source_url TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('fetched', 'not_modified', 'failed', 'skipped')
    ),
    status_code INTEGER,
    source_sha256 TEXT,
    error TEXT,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX document_versions_point_in_time_unique_idx ON document_versions (document_id, version_kind, snapshot_date)
WHERE
    snapshot_date IS NOT NULL;

CREATE UNIQUE INDEX document_versions_undated_unique_idx ON document_versions (document_id, version_kind)
WHERE
    snapshot_date IS NULL;

CREATE INDEX documents_type_year_number_idx ON documents (legislation_type, calendar_year, number);

CREATE INDEX documents_latest_version_idx ON documents (latest_version_id);

CREATE INDEX document_versions_document_idx ON document_versions (document_id, version_kind, snapshot_date);

CREATE INDEX document_files_document_idx ON document_files (document_id, file_kind);

CREATE INDEX document_files_version_idx ON document_files (version_id, file_kind);

CREATE INDEX provisions_version_ordinal_idx ON provisions (version_id, ordinal);

CREATE INDEX provisions_document_idx ON provisions (document_id);

CREATE INDEX fetch_observations_run_idx ON fetch_observations (fetch_run_id, observed_at);

CREATE INDEX fetch_observations_document_idx ON fetch_observations (document_id, observed_at);

-- +goose StatementEnd
-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS fetch_observations;

DROP TABLE IF EXISTS fetch_runs;

DROP TABLE IF EXISTS provisions;

DROP TABLE IF EXISTS document_files;

ALTER TABLE IF EXISTS documents
DROP CONSTRAINT if EXISTS documents_latest_version_id_fkey;

DROP TABLE IF EXISTS document_versions;

DROP TABLE IF EXISTS documents;

DROP TABLE IF EXISTS storage_objects;

-- +goose StatementEnd
