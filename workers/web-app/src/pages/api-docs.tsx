import { Layout } from "./layout";

const API_BASE = "https://git-legislation-read-api.british-legislation.workers.dev";

interface Endpoint {
  method: string;
  path: string;
  summary: string;
  detail?: string;
  example: string;
  params?: [string, string][];
}

const ENDPOINTS: { group: string; blurb: string; endpoints: Endpoint[] }[] = [
  {
    group: "Documents",
    blurb:
      "A document is a stable legislative identity — Immigration Act 1971 is ukpga/1971/77 " +
      "whatever it says today. Its id is the same path legislation.gov.uk uses.",
    endpoints: [
      {
        method: "GET",
        path: "/documents",
        summary: "Search and filter the corpus.",
        example: "/documents?legislation_type=ukpga&year=2010&q=equality",
        params: [
          ["legislation_type", "Series code: ukpga, uksi, asp, nia, wsi, ssi …"],
          ["year", "Calendar year"],
          ["number", "Number within the series"],
          ["status", "e.g. Prospective"],
          ["extent", "Jurisdiction, e.g. E+W+S+N.I."],
          ["metadata_only", "true/false — records with no parsed text"],
          ["q", "Substring match on the title"],
          ["sort", "default (by year) or newest (by legal date)"],
          ["limit / offset", "Paging; limit 1–500, default 50"],
        ],
      },
      {
        method: "GET",
        path: "/documents/{id}",
        summary: "One document, with its latest version nested.",
        example: "/documents/ukpga/1971/77",
      },
      {
        method: "GET",
        path: "/documents/{id}/versions",
        summary: "Every stored version, oldest first.",
        detail:
          "A version is the text as it stood on one date. Heavily amended Acts have hundreds; " +
          "most documents have one.",
        example: "/documents/ukpga/1971/77/versions",
      },
      {
        method: "GET",
        path: "/documents/{id}/effects",
        summary: "Amendments recorded against this document, or made by it.",
        example: "/documents/ukpga/2025/31/effects?direction=affecting",
        params: [
          ["direction", "affected (changes to it) or affecting (changes it made)"],
          ["textual_only", "true to exclude commencement and non-textual records"],
        ],
      },
    ],
  },
  {
    group: "Text and diffs",
    blurb:
      "Provisions are the browse units — sections, schedules — parsed out of each version. " +
      "The diff endpoint is the one you probably came for.",
    endpoints: [
      {
        method: "GET",
        path: "/diff",
        summary: "Compare two versions of the same document.",
        detail:
          "Provisions are aligned by type, number and extent, then classified as added, removed, " +
          "changed or unchanged. Each changed entry carries the effects that explain it — but only " +
          "where the provision demonstrably changed. Effects that cannot be corroborated are " +
          "returned in unattached_effects instead of being asserted against text.",
        example:
          "/diff?from=point-in-time:2025-12-02:ukpga/1971/77" +
          "&to=point-in-time:2026-05-05:ukpga/1971/77",
        params: [
          ["from", "Version id to compare from"],
          ["to", "Version id to compare to (same document)"],
        ],
      },
      {
        method: "GET",
        path: "/versions/{version_id}/provisions",
        summary: "The provisions of a version, in document order.",
        example: "/versions/point-in-time:2026-05-05:ukpga/1998/42/provisions",
      },
      {
        method: "GET",
        path: "/versions/{version_id}/provisions/{anchor}",
        summary: "One provision, with its text.",
        example:
          "/versions/point-in-time:2026-05-05:ukpga/1998/42/provisions/1-the-convention-rights",
      },
      {
        method: "GET",
        path: "/versions/{version_id}/content",
        summary: "The whole version as Markdown or as the source CLML XML.",
        detail: "Objects are stored gzipped and decompressed on the way out, so you get plain text.",
        example: "/versions/point-in-time:2026-05-05:ukpga/1998/42/content?kind=markdown",
        params: [["kind", "markdown (default) or clml_xml"]],
      },
      {
        method: "GET",
        path: "/versions/{version_id}/files",
        summary: "Stored artifacts for a version — Markdown, XML, source PDFs.",
        example: "/versions/point-in-time:2026-05-05:ukpga/1998/42/files",
      },
    ],
  },
  {
    group: "Changesets",
    blurb: "The reverse view: one amending instrument, and everything it did.",
    endpoints: [
      {
        method: "GET",
        path: "/changesets/{document_id}",
        summary: "Every effect an instrument made, grouped by the document affected.",
        detail:
          "Groups are flagged in_corpus: an instrument can amend legislation that is not published " +
          "on legislation.gov.uk, and those edges are kept rather than dropped.",
        example: "/changesets/ukpga/2025/31",
      },
    ],
  },
  {
    group: "Corpus",
    blurb: "",
    endpoints: [
      {
        method: "GET",
        path: "/corpus/summary",
        summary: "Document counts and year ranges per series.",
        example: "/corpus/summary",
      },
      { method: "GET", path: "/healthz", summary: "Liveness check.", example: "/healthz" },
    ],
  },
];

export function ApiDocsPage() {
  return (
    <Layout title="API — git-legislation" pageClass="api-page">
      <div class="landing">
        <section class="hero">
          <h1 class="landing-title">API</h1>
          <div class="hero-explainer">
            <p class="lede">
              Everything on this site is served by a read-only JSON API. No key, no sign-up, no rate
              limit beyond ordinary politeness.
            </p>
            <p>
              Base URL: <code class="api-base">{API_BASE}</code>
            </p>
            <p class="field-help">
              Version ids contain colons and slashes (
              <code>point-in-time:2026-05-05:ukpga/1971/77</code>). Both raw and percent-encoded
              forms work.
            </p>
          </div>
        </section>

        <section class="api-quickstart">
          <h2 class="section-title">Two minutes in</h2>
          <pre class="api-code">
            <code>{`# find an Act
curl "${API_BASE}/documents?q=immigration&legislation_type=ukpga"

# list the versions we hold for it
curl "${API_BASE}/documents/ukpga/1971/77/versions"

# see what changed between two of them, and why
curl "${API_BASE}/diff?from=point-in-time:2025-12-02:ukpga/1971/77&to=point-in-time:2026-05-05:ukpga/1971/77"`}</code>
          </pre>
        </section>

        {ENDPOINTS.map((section) => (
          <section class="api-section">
            <h2 class="section-title">{section.group}</h2>
            {section.blurb ? <p class="api-blurb">{section.blurb}</p> : null}
            {section.endpoints.map((endpoint) => (
              <article class="api-endpoint">
                <h3>
                  <span class="api-method">{endpoint.method}</span>
                  <code>{endpoint.path}</code>
                </h3>
                <p class="api-summary">{endpoint.summary}</p>
                {endpoint.detail ? <p class="api-detail">{endpoint.detail}</p> : null}
                {endpoint.params ? (
                  <dl class="api-params">
                    {endpoint.params.map(([name, description]) => (
                      <div class="api-param">
                        <dt>
                          <code>{name}</code>
                        </dt>
                        <dd>{description}</dd>
                      </div>
                    ))}
                  </dl>
                ) : null}
                <p class="api-example">
                  <a href={`${API_BASE}${endpoint.example}`}>{endpoint.example}</a>
                </p>
              </article>
            ))}
          </section>
        ))}

        <section class="api-section">
          <h2 class="section-title">Notes</h2>
          <ul class="api-notes">
            <li>
              <strong>Errors</strong> are <code>{`{"detail": "..."}`}</code> with 404 for missing
              records and 422 for bad parameters.
            </li>
            <li>
              <strong>Lists</strong> are wrapped as <code>{`{"items": [...]}`}</code>.
            </li>
            <li>
              <strong>Not a source of law.</strong> This is a derived research corpus. Anything that
              matters should be checked against{" "}
              <a href="https://www.legislation.gov.uk">legislation.gov.uk</a>, which is the
              authoritative text.
            </li>
            <li>
              <strong>Licensing.</strong> The underlying data is Crown copyright, published under the{" "}
              <a href="https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/">
                Open Government Licence v3.0
              </a>
              .
            </li>
          </ul>
        </section>
      </div>
    </Layout>
  );
}
