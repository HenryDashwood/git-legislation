migrate-create:
	goose -dir db/migrations create $(name) sql

migrate-up:
	set -a; . ./.env; set +a; goose -dir db/migrations postgres "$$DB_URL" up

migrate-status:
	set -a; . ./.env; set +a; goose -dir db/migrations postgres "$$DB_URL" status