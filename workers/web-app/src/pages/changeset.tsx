import type { Json } from "../api";
import { Layout } from "./layout";

export interface ChangesetProps {
  changeset: Json | null;
  error: string | null;
}

/**
 * One amending instrument as a single changeset across every document it
 * touched — the view legislation.gov.uk's per-document model cannot show.
 */
export function ChangesetPage(props: ChangesetProps) {
  const { changeset } = props;
  if (props.error !== null || changeset === null) {
    return (
      <Layout title="Changeset — git-legislation" pageClass="reader-page">
        <p class="back-link">
          <a href="/documents">&lsaquo; Back to documents</a>
        </p>
        <div class="notice error">Could not load changeset: {props.error ?? "not found"}</div>
      </Layout>
    );
  }

  const documentId = String(changeset["affecting_document_id"] ?? "");
  const title = String(changeset["affecting_title"] ?? documentId);
  const summary = (changeset["summary"] as Json | null) ?? {};
  const groups = (changeset["groups"] as Json[] | null) ?? [];

  return (
    <Layout title={`Changes made by ${title} — git-legislation`} pageClass="reader-page">
      <p class="back-link">
        <a href={`/documents/${documentId}`}>&lsaquo; Back to {title}</a>
      </p>

      <article class="document-header">
        <div class="document-title-block">
          <span class="caption">Changes made by</span>
          <h1>{title}</h1>
          <p class="metadata">
            {String(summary["effects"] ?? 0)} recorded effects across{" "}
            {String(summary["documents_affected"] ?? 0)} documents
          </p>
        </div>
        <dl class="summary-list">
          <div class="summary-row">
            <dt>Textual</dt>
            <dd>{String(summary["textual"] ?? 0)}</dd>
          </div>
          <div class="summary-row">
            <dt>Applied</dt>
            <dd>{String(summary["applied"] ?? 0)}</dd>
          </div>
          <div class="summary-row">
            <dt>Prospective</dt>
            <dd>{String(summary["prospective"] ?? 0)}</dd>
          </div>
        </dl>
      </article>

      <section class="diff-list">
        {groups.map((group) => (
          <ChangesetGroup group={group} />
        ))}
      </section>
    </Layout>
  );
}

function ChangesetGroup({ group }: { group: Json }) {
  const affectedId = String(group["affected_document_id"] ?? "");
  const inCorpus = group["in_corpus"] === true;
  const title = String(group["affected_title"] ?? affectedId ?? "Unnamed legislation");
  return (
    <article class="panel changeset-group">
      <header class="changeset-group-header">
        <h2>
          {inCorpus ? <a href={`/documents/${affectedId}`}>{title}</a> : title}
        </h2>
        <span class="metadata">
          {String(group["effect_count"] ?? 0)} effects
          {Number(group["textual_count"] ?? 0) > 0 ? <> · {String(group["textual_count"])} textual</> : null}
        </span>
      </header>
      <p class="metadata">
        {!inCorpus ? (
          <span class="changeset-absent">Not published on legislation.gov.uk, so no text to compare. </span>
        ) : null}
        {group["first_in_force"] ? (
          <>
            In force {String(group["first_in_force"])}
            {group["last_in_force"] && group["last_in_force"] !== group["first_in_force"] ? (
              <> to {String(group["last_in_force"])}</>
            ) : null}
          </>
        ) : (
          "No commencement date recorded"
        )}
        {Number(group["prospective_count"] ?? 0) > 0 ? (
          <> · {String(group["prospective_count"])} prospective</>
        ) : null}
      </p>
    </article>
  );
}
