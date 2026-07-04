# read-api Worker

TypeScript port of the Python read API (`src/git_legislation_api`), serving the
corpus from PlanetScale Postgres (via Hyperdrive) and Cloudflare R2. Response
shapes are byte-compatible with the Python service (verified by diffing both
against the same database).

Deployed at: https://git-legislation-read-api.british-legislation.workers.dev

## Local development

```bash
npm install
npm run dev        # http://127.0.0.1:8787, connects to local Postgres
npm test
npm run typecheck
```

`wrangler dev` uses the `localConnectionString` in `wrangler.jsonc` (the local
docker Postgres) and a local simulated R2 bucket. Seed dev objects when needed:

```bash
npx wrangler r2 object put 'british-legislation/<key>' --file <path> --local
```

## Deploy (one-time setup)

```bash
npx wrangler login

# Create the Hyperdrive config pointing at PlanetScale (DSN from .envrc):
npx wrangler hyperdrive create git-legislation --connection-string="$PSCALE_URL"
# Paste the returned id into wrangler.jsonc ("id": "...").

npx wrangler deploy
```

The R2 bucket binding (`british-legislation`) needs no extra setup — the
Worker reads objects through the binding, so no S3 credentials or presigned
URLs are involved.

## Routes

Same surface as the Python API: `/healthz`, `/corpus/summary`, `/documents`
(filterable), `/documents/{path}`, `/documents/{path}/versions[/latest]`,
`/versions/{id}`, `/versions/{id}/provisions[/{anchor}]`,
`/versions/{id}/files`, `/versions/{id}/content?kind=markdown|clml_xml`,
`/files/{id}/content`.

Document paths and version ids contain slashes and colons, so the handlers
match wildcard tails and peel known suffixes, mirroring FastAPI's
`{param:path}` routes.
