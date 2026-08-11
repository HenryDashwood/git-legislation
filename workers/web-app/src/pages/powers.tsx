import type { Json } from "../api";
import { ACTOR_OPTIONS, INSTRUMENT_LABELS, type PowerFilters, type SearchPlan } from "../powers";
import { Layout } from "./layout";

export interface PowersPageProps {
  question: string;
  plan: SearchPlan;
  filters: PowerFilters;
  results: Json[];
  searched: boolean;
  readStatus: "read" | "no_key" | "unavailable" | "not_attempted";
  error: string | null;
}

/** Chips carry their value in a hidden input, so removing one is a form edit. */
function ChipList(props: { name: string; values: string[]; label: string; empty: string }) {
  return (
    <div class="facet">
      <span class="facet-name">{props.label}</span>
      <div class="chips">
        {props.values.length === 0 ? <span class="facet-empty">{props.empty}</span> : null}
        {props.values.map((value) => (
          <span class="chip">
            <input type="hidden" name={props.name} value={value} />
            {value}
            <button
              type="button"
              class="chip-remove"
              aria-label={`Remove ${value}`}
              data-remove-chip
            >
              &times;
            </button>
          </span>
        ))}
        <input
          class="chip-add"
          type="text"
          name={props.name}
          value=""
          placeholder="+ add"
          aria-label={`Add to ${props.label}`}
        />
      </div>
    </div>
  );
}

function InstrumentChips(props: { selected: string[] }) {
  return (
    <div class="facet">
      <span class="facet-name">Kind of power</span>
      <div class="chips">
        {Object.entries(INSTRUMENT_LABELS)
          .filter(([key]) => key !== "other")
          .map(([key, label]) => {
            const on = props.selected.includes(key);
            return (
              <label class={`chip chip-toggle ${on ? "on" : "off"}`}>
                <input type="checkbox" name="instrument" value={key} checked={on} />
                {label}
              </label>
            );
          })}
      </div>
    </div>
  );
}

function citation(documentId: string, sectionPath: string): string {
  const label = sectionPath
    .replace(/\//g, " ")
    .replace(/^section /, "s. ")
    .replace(/^regulation /, "reg. ")
    .replace(/^article /, "art. ")
    .replace(/^rule /, "r. ")
    .replace(/^schedule /, "sch. ")
    .replace(/ paragraph /, " para. ");
  return `${label}${documentId === "" ? "" : ""}`;
}

function ResultItem(props: { row: Json; index: number }) {
  const row = props.row;
  const documentId = String(row["document_id"] ?? "");
  const sectionPath = String(row["section_path"] ?? "");
  const targets = Array.isArray(row["targets"]) ? (row["targets"] as string[]) : [];
  const isDirection = row["is_direction_power"] === true;
  const instrument = String(row["instrument"] ?? "");
  return (
    <li class="power" id={`ref${props.index}`}>
      <span class="power-num">[{props.index}]</span>
      <div>
        <p class="power-cite">
          <a href={`/documents/${documentId}`} target="_blank" rel="noopener">
            {String(row["enactment_title"] ?? "")}
          </a>
          {sectionPath === "" ? null : <span class="power-section">{citation(documentId, sectionPath)}</span>}
        </p>
        <p class="power-meta">
          <span class="badge">{String(row["actor"] ?? "")}</span>
          {isDirection ? <span class="badge badge-direction">Direction power</span> : null}
          <span class="badge">{INSTRUMENT_LABELS[instrument] ?? instrument}</span>
          {row["si_procedure"] ? <span class="badge">{String(row["si_procedure"])} procedure</span> : null}
          <span class="badge badge-score">{String(row["score"] ?? "")}</span>
        </p>
        <p class="power-text">May {String(row["action"] ?? "")}</p>
        {row["condition"] ? (
          <p class="power-limit">
            <b>Limits on its exercise</b>
            {String(row["condition"])}
          </p>
        ) : null}
        {targets.length > 0 ? (
          <p class="power-targets">
            Exercised over: {targets.slice(0, 6).join(", ")}
          </p>
        ) : null}
        {/* Reading a provision is a detour from a search, not the end of it:
            opening in a new tab keeps the results list and its scroll position. */}
        <p class="power-links">
          <a href={`/documents/${documentId}`} target="_blank" rel="noopener">
            Open in git&#8211;legislation
          </a>
          <a
            href={`https://www.legislation.gov.uk/${documentId}/${sectionPath}`}
            target="_blank"
            rel="noopener"
          >
            legislation.gov.uk
          </a>
        </p>
      </div>
    </li>
  );
}

export function PowersResults(props: PowersPageProps) {
  if (props.error !== null) {
    return <div class="notice error">Could not search powers: {props.error}</div>;
  }
  if (!props.searched) {
    return null;
  }
  if (props.results.length === 0) {
    return (
      <div class="notice">
        <p>
          <strong>Nothing here answers that.</strong>
        </p>
        <p>
          No power matched those words with those filters. Try removing a chip above, widening
          &ldquo;who holds the power&rdquo; to any actor, or searching duties as well as powers.
        </p>
      </div>
    );
  }
  return (
    <>
      <p class="results-meta">
        {props.results.length} power{props.results.length === 1 ? "" : "s"}, best match first
      </p>
      <ol class="power-list">
        {props.results.map((row, index) => (
          <ResultItem row={row} index={index + 1} />
        ))}
      </ol>
      <div class="notice-block">
        <p>
          <strong>How this was assembled.</strong> Powers were extracted from the statute book by a
          language model and are research-grade: they may contain errors or omissions, and this is
          not legal advice. Read the provision before relying on it. Text reflects the statute book
          as at 30 March 2026.
        </p>
      </div>
    </>
  );
}

export function PowersPage(props: PowersPageProps) {
  return (
    <Layout title="Powers search &mdash; git-legislation" pageClass="powers-page">
      <h1 class="page-title">What powers are available to a minister?</h1>
      <p class="page-lede">
        Ask in plain English. The wording of an Act is rarely the wording you would use, so the
        question is translated into statutory language first &mdash; and the translation is shown
        below, where you can correct it.
      </p>

      {/* A search is a full-page GET, so without this the only feedback for a
          multi-second wait is the browser's own spinner. The panel names the
          stage because reading a question (a model call) and searching are
          very different waits. */}
      <div class="searching" id="searching" role="status" aria-live="polite" hidden>
        <div class="width-container searching-inner">
          <span class="searching-bar" aria-hidden="true">
            <span class="searching-bar-fill" />
          </span>
          <span class="searching-text" id="searching-text">
            Searching&#8230;
          </span>
        </div>
      </div>

      <form class="powers-form" method="get" action="/powers">
        <div class="ask">
          <label for="q">What do you want to do?</label>
          <div class="ask-row">
            <input
              id="q"
              name="q"
              type="text"
              value={props.question}
              placeholder="force NESO to give me information about a blackout"
              autocomplete="off"
            />
            <button type="submit" name="reread" value="1">
              Search
            </button>
          </div>
        </div>

        <div class="powers-layout">
          <div>
            {props.searched ? (
              <div class="reading">
                <h2>How your question was read</h2>
                <p class={`sub ${props.readStatus === "unavailable" ? "sub-warning" : ""}`}>
                  {props.readStatus === "read"
                    ? "Everything here is editable. Change it and search again — this is the filter panel, it just filled itself in first."
                    : props.readStatus === "unavailable"
                      ? "The translation service did not respond in time, so this is your wording as typed — results will be narrower than usual. Search again to retry, or add statutory wording by hand."
                      : props.readStatus === "no_key"
                        ? "Question translation is switched off (no OPENROUTER_API_KEY), so this is your wording as typed. Add statutory wording by hand."
                        : "Editing these chips changes the search without re-reading the question."}
                </p>
                <ChipList
                  name="target"
                  label="Bodies concerned"
                  values={props.plan.targets}
                  empty="No body named — searching all powers"
                />
                <InstrumentChips selected={props.plan.instruments} />
                <ChipList
                  name="term"
                  label="Statutory wording"
                  values={props.plan.terms}
                  empty="No wording — add some, or ask a question above"
                />
                <ChipList name="domain" label="Subject area" values={props.plan.domain} empty="Any subject" />
                <div class="rerun">
                  <button type="submit">Search again with these</button>
                  <span class="rerun-note">Editing a chip does not re-read the question.</span>
                </div>
              </div>
            ) : null}

            <PowersResults {...props} />
          </div>

          <aside>
            <div class="filters">
              <h2 class="filters-heading">Narrow it</h2>
              <label>
                Who holds the power
                <select name="actor">
                  {ACTOR_OPTIONS.map(([value, label]) => (
                    <option value={value} selected={props.filters.actor === value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Power or duty
                <select name="modality">
                  <option value="power" selected={props.filters.modality === "power"}>
                    Powers (may)
                  </option>
                  <option value="duty" selected={props.filters.modality === "duty"}>
                    Duties (must)
                  </option>
                  <option value="both" selected={props.filters.modality === "both"}>
                    Both
                  </option>
                </select>
              </label>
              <label>
                Legislation
                <select name="legislation_kind">
                  <option value="all" selected={props.filters.legislationKind === "all"}>
                    Acts and instruments
                  </option>
                  <option value="primary" selected={props.filters.legislationKind === "primary"}>
                    Acts only
                  </option>
                  <option value="secondary" selected={props.filters.legislationKind === "secondary"}>
                    Statutory instruments only
                  </option>
                </select>
              </label>
              <fieldset>
                <legend>Only show</legend>
                <span class="check">
                  <input
                    type="checkbox"
                    id="direction_only"
                    name="direction_only"
                    checked={props.filters.directionOnly}
                  />
                  <label for="direction_only">Powers of direction over another body</label>
                </span>
                <span class="check">
                  <input
                    type="checkbox"
                    id="with_conditions_only"
                    name="with_conditions_only"
                    checked={props.filters.withConditionsOnly}
                  />
                  <label for="with_conditions_only">Powers with conditions attached</label>
                </span>
              </fieldset>
              <div class="filter-actions">
                <button type="submit">Apply</button>
                <a href="/powers">Clear</a>
              </div>
            </div>
          </aside>
        </div>
      </form>

      <script
        dangerouslySetInnerHTML={{
          __html: `
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-remove-chip]");
  if (button === null) return;
  button.closest(".chip").remove();
  document.querySelector(".rerun-note")?.classList.add("changed");
});

// Reveal the searching panel on submit. A re-read costs a model call on top
// of the search, so it gets its own wording and a warning that it is slower.
document.querySelector(".powers-form")?.addEventListener("submit", (event) => {
  const rereading = event.submitter?.name === "reread";
  const panel = document.getElementById("searching");
  const text = document.getElementById("searching-text");
  if (panel === null || text === null) return;
  text.textContent = rereading
    ? "Reading your question, then searching 766,191 powers\\u2026 this takes a few seconds"
    : "Searching 766,191 powers\\u2026";
  panel.hidden = false;
  // Deferred: a disabled control is omitted from the form data, so disabling
  // the submit button synchronously would drop its own name=value and the
  // question would never be re-read.
  const form = event.currentTarget;
  setTimeout(() => {
    for (const button of form.querySelectorAll("button")) {
      button.disabled = true;
    }
  }, 0);
});

// Restore the form when the page comes back from the browser cache, so the
// back button never lands on a permanently disabled search.
window.addEventListener("pageshow", () => {
  const panel = document.getElementById("searching");
  if (panel !== null) panel.hidden = true;
  for (const button of document.querySelectorAll(".powers-form button")) {
    button.disabled = false;
  }
});
`,
        }}
      />
    </Layout>
  );
}
