import type { Json } from "../api";
import { renderWordDiff } from "../diff";
import { Layout } from "./layout";

export interface DiffProps {
  document: Json | null;
  diff: Json | null;
  error: string | null;
}

export function DiffPage(props: DiffProps) {
  const { document, diff } = props;
  if (props.error !== null || diff === null) {
    return (
      <Layout title="Compare versions — git-legislation" pageClass="reader-page">
        <p class="back-link">
          <a href="/documents">&lsaquo; Back to documents</a>
        </p>
        <div class="notice error">Could not compute diff: {props.error ?? "not found"}</div>
      </Layout>
    );
  }

  const from = (diff["from"] as Json | null) ?? {};
  const to = (diff["to"] as Json | null) ?? {};
  const summary = (diff["summary"] as Json | null) ?? {};
  const entries = ((diff["entries"] as Json[] | null) ?? []).filter(
    (entry) => entry["status"] !== "unchanged",
  );
  const unchangedCount = Number(summary["unchanged"] ?? 0);
  const documentId = String(diff["document_id"] ?? "");
  const title = document !== null ? String(document["title"] ?? documentId) : documentId;

  return (
    <Layout title={`Changes — ${title} — git-legislation`} pageClass="reader-page">
      <p class="back-link">
        <a href={`/documents/${documentId}`}>&lsaquo; Back to {title}</a>
      </p>

      <article class="document-header">
        <div class="document-title-block">
          <span class="caption">Changes between versions</span>
          <h1>{title}</h1>
          <p class="metadata">
            {versionLabel(from)} &rarr; {versionLabel(to)}
          </p>
        </div>
        <dl class="summary-list">
          <div class="summary-row">
            <dt>Changed</dt>
            <dd>{String(summary["changed"] ?? 0)}</dd>
          </div>
          <div class="summary-row">
            <dt>Added</dt>
            <dd>{String(summary["added"] ?? 0)}</dd>
          </div>
          <div class="summary-row">
            <dt>Removed</dt>
            <dd>{String(summary["removed"] ?? 0)}</dd>
          </div>
          <div class="summary-row">
            <dt>Unchanged</dt>
            <dd>{unchangedCount}</dd>
          </div>
        </dl>
      </article>

      {entries.length === 0 ? (
        <div class="notice">
          These two versions have identical provision text ({unchangedCount} provisions).
        </div>
      ) : (
        <section class="diff-list">
          {entries.map((entry) => (
            <DiffEntryCard entry={entry} />
          ))}
          {unchangedCount > 0 ? (
            <p class="metadata diff-unchanged-note">
              {unchangedCount} unchanged provision{unchangedCount === 1 ? "" : "s"} hidden.
            </p>
          ) : null}
        </section>
      )}

      <UnattachedEffects effects={(diff["unattached_effects"] as Json[] | null) ?? []} />
    </Layout>
  );
}

function DiffEntryCard({ entry }: { entry: Json }) {
  const status = String(entry["status"] ?? "");
  const heading = String(entry["heading"] ?? entry["number"] ?? "Provision");
  const fromMarkdown = String(entry["from_markdown"] ?? "");
  const toMarkdown = String(entry["to_markdown"] ?? "");
  const effects = (entry["effects"] as Json[] | undefined) ?? [];
  return (
    <article class={`panel diff-entry diff-${status}`}>
      <header class="diff-entry-header">
        <span class={`diff-badge diff-badge-${status}`}>{status}</span>
        <h2>{heading}</h2>
      </header>
      {effects.length > 0 ? (
        <div class="diff-attribution">
          {effects.map((effect) => (
            <p>
              <span class="diff-attribution-type">{String(effect["effect_type"] ?? "amended")}</span> by{" "}
              {effect["affecting_document_id"] ? (
                <a href={`/changesets/${effect["affecting_document_id"]}`}>
                  {String(effect["affecting_title"] ?? effect["affecting_document_id"])}
                </a>
              ) : (
                String(effect["affecting_title"] ?? "an unrecorded instrument")
              )}
              {effect["affecting_provisions"] ? <> {String(effect["affecting_provisions"])}</> : null}
              {effect["in_force_date"] ? (
                <span class="diff-attribution-date"> · in force {String(effect["in_force_date"])}</span>
              ) : null}
              {effect["commencement_authority"] ? (
                <span class="diff-attribution-date">
                  {" "}
                  · commenced by {String(effect["commencement_authority"])}
                </span>
              ) : null}
            </p>
          ))}
        </div>
      ) : null}
      {status === "changed" ? (
        <pre
          class="diff-text"
          dangerouslySetInnerHTML={{ __html: renderWordDiff(fromMarkdown, toMarkdown) }}
        />
      ) : status === "added" ? (
        <pre class="diff-text diff-text-added">{toMarkdown}</pre>
      ) : (
        <pre class="diff-text diff-text-removed">{fromMarkdown}</pre>
      )}
    </article>
  );
}

/**
 * Amendments the register records in this window that we could not tie to a
 * changed provision. Shown as a plain list rather than pinned to any text: the
 * register and the revised text sometimes disagree, and a wrong attribution is
 * worse than an unplaced one.
 */
function UnattachedEffects({ effects }: { effects: Json[] }) {
  if (effects.length === 0) {
    return null;
  }
  return (
    <section class="panel diff-unattached">
      <h2>Other recorded amendments in this window</h2>
      <p class="metadata">
        The Changes to Legislation register lists these for the same period, but we could not match
        them to a provision whose text changed between these two versions.
      </p>
      <ul class="compact-list">
        {effects.map((effect) => (
          <li>
            <strong>{String(effect["affected_provisions"] ?? "unspecified provision")}</strong>{" "}
            {String(effect["effect_type"] ?? "amended")}
            {effect["affecting_title"] ? <> by {String(effect["affecting_title"])}</> : null}
            {effect["in_force_date"] ? (
              <span class="metadata"> · in force {String(effect["in_force_date"])}</span>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

function versionLabel(version: Json): string {
  const snapshot = version["snapshot_date"];
  if (snapshot) {
    return String(snapshot);
  }
  return String(version["version_kind"] ?? version["id"] ?? "unknown");
}
