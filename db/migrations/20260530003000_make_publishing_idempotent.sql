-- +goose Up
-- +goose StatementBegin
ALTER TABLE fetch_runs
DROP CONSTRAINT fetch_runs_mode_check;

ALTER TABLE fetch_runs
ADD CONSTRAINT fetch_runs_mode_check CHECK (
    mode IN (
        'enacted',
        'point_in_time',
        'current',
        'publication_log',
        'publish',
        'other'
    )
);

DROP INDEX IF EXISTS document_versions_point_in_time_unique_idx;

CREATE INDEX IF NOT EXISTS document_versions_point_in_time_idx ON document_versions (document_id, version_kind, snapshot_date)
WHERE
    snapshot_date IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS document_versions_content_unique_idx ON document_versions (
    document_id,
    version_kind,
    source_sha256,
    markdown_sha256
)
WHERE
    markdown_sha256 IS NOT NULL;

CREATE INDEX IF NOT EXISTS fetch_observations_version_idx ON fetch_observations (version_id, observed_at);

-- +goose StatementEnd
-- +goose Down
-- +goose StatementBegin
DROP INDEX IF EXISTS fetch_observations_version_idx;

DROP INDEX IF EXISTS document_versions_content_unique_idx;

DROP INDEX IF EXISTS document_versions_point_in_time_idx;

CREATE UNIQUE INDEX IF NOT EXISTS document_versions_point_in_time_unique_idx ON document_versions (document_id, version_kind, snapshot_date)
WHERE
    snapshot_date IS NOT NULL;

ALTER TABLE fetch_runs
DROP CONSTRAINT fetch_runs_mode_check;

ALTER TABLE fetch_runs
ADD CONSTRAINT fetch_runs_mode_check CHECK (
    mode IN (
        'enacted',
        'point_in_time',
        'current',
        'publication_log',
        'other'
    )
);

-- +goose StatementEnd
