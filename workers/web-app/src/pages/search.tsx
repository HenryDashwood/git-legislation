import { METADATA_OPTIONS, SERIES, STATUS_OPTIONS, TYPE_LABELS, citation } from "../legislation";
import type { Json } from "../api";
import { Layout } from "./layout";

export interface Filters {
  legislation_type: string;
  year: string;
  number: string;
  status: string;
  extent: string;
  metadata_only: string;
  q: string;
}

export interface ResultsProps {
  documents: Json[];
  offset: number;
  error: string | null;
  prevUrl: string | null;
  nextUrl: string | null;
}

export function Results(props: ResultsProps) {
  if (props.error !== null) {
    return <div class="notice error">Could not load documents: {props.error}</div>;
  }
  if (props.documents.length === 0) {
    return (
      <div class="notice">
        <p>No documents matched those filters.</p>
        <p>Try removing a filter, or check the number and year against the citation.</p>
      </div>
    );
  }
  return (
    <>
      <p class="results-meta">
        Showing results {props.offset + 1}&#8211;{props.offset + props.documents.length}
      </p>
      <ul class="result-list">
        {props.documents.map((document) => (
          <li class="result-item">
            <h3 class="result-title">
              <a href={`/documents/${document["id"]}`}>{document["title"]}</a>
            </h3>
            <p class="result-detail">
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
            </p>
          </li>
        ))}
      </ul>
      {props.prevUrl !== null || props.nextUrl !== null ? (
        <nav class="pagination" aria-label="Pagination">
          {props.prevUrl !== null ? (
            <a class="pagination-link" href={props.prevUrl}>
              &lsaquo; Previous page
            </a>
          ) : null}
          {props.nextUrl !== null ? (
            <a class="pagination-link pagination-next" href={props.nextUrl}>
              Next page &rsaquo;
            </a>
          ) : null}
        </nav>
      ) : null}
    </>
  );
}

export function SearchPage(props: { filters: Filters; results: ResultsProps }) {
  const { filters } = props;
  return (
    <Layout title="Search results — git-legislation">
      <p class="back-link">
        <a href="/documents">&lsaquo; Search home</a>
      </p>
      <h1 class="page-title">Search results</h1>

      <div class="finder">
        <form class="filters" action="/documents" method="get">
          <h2 class="filters-heading">Filter</h2>
          <label>
            <span class="label-text">Title contains</span>
            <input name="q" value={filters.q} />
          </label>
          <label>
            <span class="label-text">Type</span>
            <select name="legislation_type">
              <option value="">All types</option>
              {SERIES.map((series) => (
                <option value={series.code} selected={filters.legislation_type === series.code}>
                  {series.label} ({series.code})
                </option>
              ))}
            </select>
          </label>
          <label>
            <span class="label-text">Year</span>
            <input name="year" type="number" value={filters.year} />
          </label>
          <label>
            <span class="label-text">Number</span>
            <input name="number" value={filters.number} />
            <span class="field-help">
              The numbered item within a type and year, for example chapter 14.
            </span>
          </label>
          <label>
            <span class="label-text">Status</span>
            <select name="status">
              <option value="">Any status</option>
              {STATUS_OPTIONS.map((status) => (
                <option value={status} selected={filters.status === status}>
                  {status}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span class="label-text">Extent</span>
            <input name="extent" value={filters.extent} />
            <span class="field-help">Jurisdiction codes joined with +: E, W, S and N.I.</span>
          </label>
          <label>
            <span class="label-text">Text coverage</span>
            <select name="metadata_only">
              {METADATA_OPTIONS.map((option) => (
                <option value={option.value} selected={filters.metadata_only === option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <span class="field-help">
              Metadata or PDF&#8209;backed records may not have parsed text yet.
            </span>
          </label>
          <div class="filter-actions">
            <button type="submit" class="button">
              Apply filters
            </button>
            <a class="secondary-action" href="/documents">
              Clear
            </a>
          </div>
        </form>

        <section id="document-results" class="results-column">
          <Results {...props.results} />
        </section>
      </div>
    </Layout>
  );
}
