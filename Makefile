migrate-create:
	goose -dir db/migrations create $(name) sql

migrate-up:
	set -a; . ./.env; set +a; goose -dir db/migrations postgres "$$DB_URL" up
	$(MAKE) db-dump

migrate-status:
	set -a; . ./.env; set +a; goose -dir db/migrations postgres "$$DB_URL" status

db-dump:
	set -a; . ./.env; set +a; pg_dump --schema-only --no-owner --no-privileges --no-comments --restrict-key=british_legislation_schema "$$DB_URL" > db/schema.sql