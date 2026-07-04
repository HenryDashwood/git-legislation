# web-app Worker

TypeScript port of the Python HTMX web app (`web-app/`), rendered with Hono JSX
on Cloudflare Workers. Calls the read API through a service binding
(`git-legislation-read-api`) — zero-latency worker-to-worker, no public hop.

The HTMX interaction model, URL scheme, and CSS are unchanged from the Python
app; `public/static/app.css` is served via Workers static assets.

## Local development

```bash
npm install
npm run dev        # http://127.0.0.1:8788 — runs BOTH workers locally
npm test
npm run typecheck
```

`npm run dev` starts this Worker plus the read-api Worker (via
`-c ../read-api/wrangler.jsonc`), so the service binding resolves locally: the
read API connects to local docker Postgres and a local simulated R2 bucket.
Seed content objects for the pages you're testing:

```bash
npx wrangler r2 object put 'british-legislation/<key>' --file <path> --local --persist-to .wrangler/state
```

## Deploy

```bash
npx wrangler deploy
```

The service binding targets the deployed `git-legislation-read-api` Worker;
the PDF proxy uses the Cache API so the browser PDF viewer's double-fetch and
repeat views never re-hit legislation.gov.uk.
