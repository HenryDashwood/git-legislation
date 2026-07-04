import { SERIES } from "../legislation";
import type { Timeline } from "../timeline";
import { Layout } from "./layout";

export function LandingPage(props: { timeline: Timeline }) {
  const { timeline } = props;
  return (
    <Layout title="git-legislation — the statute book, under version control">
      <div class="landing">
        <section class="hero">
          <h1 class="landing-title">
            The statute book,
            <br />
            under version control.
          </h1>
          <div class="hero-explainer">
            <p class="lede">
              git&#8211;legislation is a research mirror of{" "}
              <a href="https://www.legislation.gov.uk">legislation.gov.uk</a>: every Act and
              statutory instrument from every UK legislature, captured as reproducible
              point&#8209;in&#8209;time snapshots
              {timeline.totalLabel ? (
                <>
                  {" "}
                  &#8212; {timeline.totalLabel} documents and counting
                </>
              ) : null}
              .
            </p>
            <dl class="offer-list">
              <div class="offer">
                <dt>Search the corpus</dt>
                <dd>Filter by series, year, number, status, and jurisdictional extent.</dd>
              </div>
              <div class="offer">
                <dt>Read side by side</dt>
                <dd>Parsed statute text next to the source PDF it was derived from.</dd>
              </div>
              <div class="offer">
                <dt>Trace the record</dt>
                <dd>
                  Snapshots record the law as it stood on a given date, so results can be
                  reproduced.
                </dd>
              </div>
            </dl>
          </div>
        </section>

        <section class="search-section">
          <h2 class="section-title">Find a document</h2>
          <form class="search-hero" action="/documents" method="get" role="search">
            <div class="search-grid">
              <label class="search-field grow">
                <span class="label-text">Title contains</span>
                <input
                  id="landing-q"
                  name="q"
                  type="search"
                  spellcheck={false}
                  autocomplete="off"
                  placeholder="e.g. official secrets"
                />
              </label>
              <label class="search-field">
                <span class="label-text">Series</span>
                <select name="legislation_type">
                  <option value="">All series</option>
                  {SERIES.map((series) => (
                    <option value={series.code}>{series.label}</option>
                  ))}
                </select>
              </label>
              <label class="search-field year-field">
                <span class="label-text">Year</span>
                <input name="year" type="number" placeholder="1998" />
              </label>
              <button type="submit" class="button search-button">
                Search
              </button>
            </div>
            <p class="field-help">
              More filters &#8212; status, extent, text coverage &#8212; are on the results page.
            </p>
          </form>
        </section>

        <section class="timeline-section">
          <h2 class="section-title">Eight centuries of law</h2>
          <p class="timeline-intro">
            Everything here belongs to one of 25 series, from the Acts of the English Parliament (
            {timeline.startYear}) to the devolved legislatures. Choose a series to start reading.
          </p>

          <div class="timeline">
            <div class="timeline-row timeline-scale" aria-hidden="true">
              <span class="timeline-label"></span>
              <span class="timeline-track">
                {timeline.ticks.map((tick) => (
                  <span class="timeline-tick" style={`left: ${tick.leftPct}%`}>
                    {tick.year}
                  </span>
                ))}
              </span>
              <span class="timeline-meta"></span>
            </div>
            {timeline.groups.map((group) => (
              <>
                <h3 class={`timeline-group-title mark-${group.slug}`}>{group.title}</h3>
                {group.rows.map((row) => (
                  <a class="timeline-row" href={`/documents?legislation_type=${row.code}`}>
                    <span class="timeline-label">{row.label}</span>
                    <span class="timeline-track">
                      <span
                        class={`timeline-bar bar-${group.slug}`}
                        style={`left: ${row.leftPct}%; width: ${row.widthPct}%`}
                      ></span>
                    </span>
                    <span class="timeline-meta">
                      {row.firstYear}&#8211;{row.lastLabel}
                      {row.countLabel ? <> &middot; {row.countLabel}</> : null}
                    </span>
                  </a>
                ))}
              </>
            ))}
          </div>
        </section>
      </div>
    </Layout>
  );
}
