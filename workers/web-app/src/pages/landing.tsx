import { SERIES } from "../legislation";
import type { Json } from "../api";
import type { Timeline } from "../timeline";
import { Layout } from "./layout";
import { FeedRow } from "./recent";

/** Worked examples, kept concrete: each links to a page that demonstrates one capability. */
const EXAMPLES = [
  {
    href:
      "/diff?from=point-in-time:2025-12-02:ukpga/1971/77" +
      "&to=point-in-time:2026-05-05:ukpga/1971/77",
    title: "What changed in the Immigration Act 1971 last spring",
    body:
      "Five provisions changed, each labelled with the Act that changed it and the date it came " +
      "into force. Section 24 gained a new offence; the words are highlighted where they differ.",
  },
  {
    href: "/changesets/ukpga/2025/31",
    title: "Everything the Border Security Act 2025 changed",
    body:
      "One instrument, 90 recorded effects across 7 other Acts, grouped by the Act affected. " +
      "The reverse of the usual view: not this law's history, but this law's consequences.",
  },
  {
    href:
      "/diff?from=point-in-time:2025-08-01:ukpga/1990/43" +
      "&to=point-in-time:2025-11-01:ukpga/1990/43",
    title: "A Scottish-only amendment, kept separate",
    body:
      "The Environmental Protection Act reads differently in Scotland. Scottish regulations " +
      "amended the Scottish text, and the diff shows those provisions on their own.",
  },
];

export function LandingPage(props: { timeline: Timeline; recent: Json[] }) {
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
              statutory instrument from every UK legislature
              {timeline.totalLabel ? <> &#8212; {timeline.totalLabel} documents</> : null}, captured
              as point&#8209;in&#8209;time snapshots you can compare.
            </p>
            <dl class="offer-list">
              <div class="offer">
                <dt>See what changed</dt>
                <dd>
                  Compare any two dates in an Act's life and read the difference word by word,
                  section by section.
                </dd>
              </div>
              <div class="offer">
                <dt>Find out why</dt>
                <dd>
                  Each change is attributed to the instrument that made it, with the date it came
                  into force.
                </dd>
              </div>
              <div class="offer">
                <dt>Follow one instrument</dt>
                <dd>
                  See everything a single amending Act did, across every law it touched, on one
                  page.
                </dd>
              </div>
              <div class="offer">
                <dt>Build on the data</dt>
                <dd>
                  Everything on this site comes from a <a href="/api">public JSON API</a>. No key,
                  no sign&#8209;up.
                </dd>
              </div>
            </dl>
          </div>
        </section>

        <section class="examples-section">
          <h2 class="section-title">Start here</h2>
          <div class="example-grid">
            {EXAMPLES.map((example) => (
              <a class="example-card" href={example.href}>
                <h3>{example.title}</h3>
                <p>{example.body}</p>
              </a>
            ))}
          </div>
        </section>

        <section class="difference-section">
          <h2 class="section-title">How this differs from legislation.gov.uk</h2>
          <p class="difference-lede">
            legislation.gov.uk is the official source and the only authoritative one. This site is
            derived from it, and exists to answer a question the official site does not: not what
            the law says now, but <em>what changed, when, and because of what</em>.
          </p>
          <div class="difference-grid">
            <div class="difference-col">
              <h3>legislation.gov.uk gives you</h3>
              <ul>
                <li>The authoritative text, as amended</li>
                <li>A list of the versions that exist</li>
                <li>
                  A register of amendments &#8212; which instrument changed which provision, and
                  when
                </li>
                <li>Editorial annotations and footnotes on the text</li>
              </ul>
            </div>
            <div class="difference-col">
              <h3>This site adds</h3>
              <ul>
                <li>
                  <strong>The actual textual difference</strong> between two dates, aligned
                  provision by provision
                </li>
                <li>
                  <strong>Those two datasets joined</strong>: the amendment register attached to the
                  words it changed
                </li>
                <li>
                  <strong>The changeset view</strong>: one instrument across every law it touched
                </li>
                <li>
                  <strong>A JSON API</strong> over all of it
                </li>
              </ul>
            </div>
          </div>
          <p class="difference-caveat">
            This is an experimental research corpus, not a source of law &#8212;
            check anything that matters against{" "}
            <a href="https://www.legislation.gov.uk">the official text</a>. And amendment
            attributions are only shown where the recorded change can be corroborated against a
            provision that demonstrably changed; where the register and the text disagree, we say so
            rather than guess.
          </p>
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

        {props.recent.length > 0 ? (
          <section class="recent-section">
            <h2 class="section-title">Recently made</h2>
            <ul class="result-list recent-preview">
              {props.recent.map((document) => (
                <FeedRow document={document} />
              ))}
            </ul>
            <p class="recent-more">
              <a href="/recent">Browse the full feed, newest to oldest &rsaquo;</a>
            </p>
          </section>
        ) : null}

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
