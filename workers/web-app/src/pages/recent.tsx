import { TYPE_LABELS, citation } from "../legislation";
import type { Json } from "../api";
import { Layout } from "./layout";

const FEED_PAGE_SIZE = 50;

export function legalDateLabel(document: Json): string | null {
  const date = document["legal_date"];
  if (typeof date !== "string" || date === "") {
    return null;
  }
  const formatted = new Date(`${date}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
  const kind = document["legal_date_kind"] === "enacted" ? "Royal Assent" : "Made";
  return `${kind} ${formatted}`;
}

function coverageLabel(document: Json): string | null {
  const metadataOnly = document["latest_is_metadata_only"];
  if (metadataOnly === true) {
    return "PDF-backed";
  }
  if (metadataOnly === false) {
    const words = document["latest_word_count"];
    if (typeof words === "number" && words > 0) {
      return `Full text, ${words.toLocaleString("en-GB")} words`;
    }
    return "Full text";
  }
  return null;
}

export function FeedRow(props: { document: Json }) {
  const { document } = props;
  const coverage = coverageLabel(document);
  const legalDate = legalDateLabel(document);
  return (
    <li class="result-item">
      <h3 class="result-title">
        <a href={`/documents/${document["id"]}`}>{document["title"]}</a>
      </h3>
      <p class="result-detail">
        {legalDate !== null ? (
          <>
            <strong class="result-date">{legalDate}</strong>
            <span class="separator">&middot;</span>{" "}
          </>
        ) : null}
        {TYPE_LABELS[String(document["legislation_type"])] ?? document["legislation_type"]}
        <span class="separator">&middot;</span>{" "}
        {citation(String(document["legislation_type"]), document["year"], document["number"])}
        {document["extent"] ? (
          <>
            <span class="separator">&middot;</span> {document["extent"]}
          </>
        ) : null}
        {document["status"] ? (
          <>
            <span class="separator">&middot;</span> {document["status"]}
          </>
        ) : null}
        {coverage !== null ? (
          <>
            <span class="separator">&middot;</span> {coverage}
          </>
        ) : null}
      </p>
    </li>
  );
}

export function FeedItems(props: { documents: Json[]; offset: number; error: string | null }) {
  if (props.error !== null) {
    return <li class="notice error">Could not load the feed: {props.error}</li>;
  }
  const hasMore = props.documents.length === FEED_PAGE_SIZE;
  return (
    <>
      {props.documents.map((document) => (
        <FeedRow document={document} />
      ))}
      {hasMore ? (
        <li
          class="feed-sentinel"
          hx-get={`/recent/items?offset=${props.offset + FEED_PAGE_SIZE}`}
          hx-trigger="revealed"
          hx-swap="outerHTML"
        >
          <span class="metadata">Loading more&hellip;</span>
        </li>
      ) : (
        <li class="feed-end">
          <span class="metadata">You have reached the beginning of the corpus.</span>
        </li>
      )}
    </>
  );
}

export function RecentPage(props: { documents: Json[]; error: string | null }) {
  return (
    <Layout title="Recent legislation — git-legislation">
      <p class="back-link">
        <a href="/documents">&lsaquo; Search home</a>
      </p>
      <h1 class="page-title">Recent legislation</h1>
      <p class="lede feed-lede">
        Every Act and instrument in the corpus, newest first &#8212; instruments by the date
        they were made, Acts by Royal Assent. Records whose date is only in a scanned PDF
        appear at the start of their year. Keep scrolling to go back in time.
      </p>
      <ul class="result-list feed-list">
        <FeedItems documents={props.documents} offset={0} error={props.error} />
      </ul>
    </Layout>
  );
}

export { FEED_PAGE_SIZE };
