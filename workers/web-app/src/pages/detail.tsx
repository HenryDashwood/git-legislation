import { TYPE_LABELS, citation, CHAPTER_CITED_TYPES } from "../legislation";
import type { Json } from "../api";
import { Layout } from "./layout";

export interface DetailProps {
  document: Json | null;
  versions: Json[];
  renderedContent: string;
  contentLabel: string;
  pdfFile: Json | null;
  error: string | null;
}

export function DetailPage(props: DetailProps) {
  const { document } = props;
  if (props.error !== null || document === null) {
    return (
      <Layout title="Document — git-legislation" pageClass="reader-page">
        <p class="back-link">
          <a href="/documents">&lsaquo; Back to documents</a>
        </p>
        <div class="notice error">Could not load document: {props.error ?? "not found"}</div>
      </Layout>
    );
  }

  const legislationType = String(document["legislation_type"] ?? "");
  const typeLabel = TYPE_LABELS[legislationType] ?? null;
  const latest = (document["latest_version"] as Json | null) ?? null;
  const pdfSourceUrl = props.pdfFile !== null ? String(props.pdfFile["source_url"] ?? "") : "";

  return (
    <Layout title={`${document["title"]} — git-legislation`} pageClass="reader-page">
      <p class="back-link">
        <a href="/documents">&lsaquo; Back to documents</a>
      </p>

      <article class="document-header">
        <div class="document-title-block">
          {typeLabel !== null ? <span class="caption">{typeLabel}</span> : null}
          <h1>{document["title"]}</h1>
          {document["document_uri"] ? (
            <p class="document-source">
              <a class="source-link" href={String(document["document_uri"])}>
                View on legislation.gov.uk
              </a>
            </p>
          ) : null}
        </div>
        <dl class="summary-list">
          <div class="summary-row">
            <dt>Identifier</dt>
            <dd>{document["id"]}</dd>
          </div>
          <div class="summary-row">
            <dt>Citation</dt>
            <dd>{citation(legislationType, document["year"], document["number"])}</dd>
          </div>
          {document["status"] ? (
            <div class="summary-row">
              <dt>Status</dt>
              <dd>{document["status"]}</dd>
            </div>
          ) : null}
          {document["extent"] ? (
            <div class="summary-row">
              <dt>Extent</dt>
              <dd>
                {document["extent"]}{" "}
                <span class="field-help">
                  (E England, W Wales, S Scotland, N.I. Northern Ireland)
                </span>
              </dd>
            </div>
          ) : null}
        </dl>
      </article>

      {latest !== null ? (
        <section class="reader-shell">
          <input class="source-toggle-checkbox" id="source-toggle" type="checkbox" checked />
          <div class="reader-toolbar">
            <div class="reader-toolbar-title">
              <h2>Parsed law</h2>
              <p class="metadata">
                {props.contentLabel} &middot; {latest["id"]} &middot; {latest["version_kind"]}
                {latest["snapshot_date"] ? <> &middot; {latest["snapshot_date"]}</> : null}
              </p>
            </div>
            {pdfSourceUrl !== "" ? (
              <div class="reader-toolbar-title source-title">
                <h2>Check against source PDF</h2>
                <p class="metadata">Proxied here for side-by-side comparison.</p>
              </div>
            ) : null}
            <div class="actions">
              {pdfSourceUrl !== "" ? (
                <>
                  <label class="button button-secondary toggle-source" for="source-toggle">
                    <span class="when-source-visible">Hide PDF</span>
                    <span class="when-source-hidden">Show PDF</span>
                  </label>
                  <a class="button button-secondary" href={pdfSourceUrl}>
                    Open PDF in a new tab
                  </a>
                </>
              ) : null}
              <button
                class="button button-secondary"
                hx-get={`/versions/${latest["id"]}/provisions`}
                hx-target="#version-panel"
              >
                Provisions
              </button>
              <button
                class="button button-secondary"
                hx-get={`/versions/${latest["id"]}/files`}
                hx-target="#version-panel"
              >
                Files
              </button>
              <button
                class="button button-secondary"
                hx-get={`/versions/${latest["id"]}/content`}
                hx-target="#version-panel"
              >
                Raw Markdown
              </button>
            </div>
          </div>

          <div class="reader-grid">
            <section class="law-content" aria-label="Parsed legislation content">
              {props.renderedContent !== "" ? (
                <div dangerouslySetInnerHTML={{ __html: props.renderedContent }} />
              ) : (
                <div class="notice">No parsed Markdown content is available for this version.</div>
              )}
            </section>

            <aside class="source-panel" aria-label="Source material">
              {pdfSourceUrl !== "" ? (
                <iframe title="Source PDF preview" src={`/versions/${latest["id"]}/pdf`}></iframe>
              ) : (
                <>
                  <div class="notice">
                    No PDF alternative is recorded for this version. Use the source URI or file
                    list instead.
                  </div>
                  <div class="source-panel-footer">
                    <a href={String(document["document_uri"] ?? "")}>Open source URI</a>
                  </div>
                </>
              )}
            </aside>
          </div>
        </section>
      ) : null}

      <section class="panel">
        <h2>Versions</h2>
        {props.versions.length > 0 ? (
          <ul class="compact-list">
            {props.versions.map((version) => (
              <li>
                {version["id"]}
                {version["snapshot_date"] ? <> ({version["snapshot_date"]})</> : null}
              </li>
            ))}
          </ul>
        ) : (
          <p>No versions found.</p>
        )}
      </section>

      <section id="version-panel" class="panel">
        <p>Select provisions, files, or content for the latest version.</p>
      </section>
    </Layout>
  );
}

export { CHAPTER_CITED_TYPES };
