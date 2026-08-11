migrate-create:
	goose -dir db/migrations create $(name) sql

migrate-up:
	set -a; . ./.env; set +a; goose -dir db/migrations postgres "$$DB_URL" up
	$(MAKE) db-dump

migrate-status:
	set -a; . ./.env; set +a; goose -dir db/migrations postgres "$$DB_URL" status

db-dump:
	set -a; . ./.env; set +a; pg_dump --schema-only --no-owner --no-privileges --no-comments --restrict-key=britishlegislationschema "$$DB_URL" > db/schema.sql
# ---- local development -------------------------------------------------
# Two workers: read-api holds the Postgres connection, web-app serves the
# pages and talks to it over a service binding. Run them in two terminals;
# web-app finds read-api automatically once it is up.
#
# The Hyperdrive binding is pointed at the real database through wrangler's
# per-binding override, so the connection string stays in .envrc and never
# reaches a committed file.

dev-api:
	. ./.envrc && cd workers/read-api && \
	WRANGLER_HYPERDRIVE_LOCAL_CONNECTION_STRING_HYPERDRIVE="$$DB_URL" \
	npx wrangler dev

dev-web:
	cd workers/web-app && npx wrangler dev
