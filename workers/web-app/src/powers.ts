/**
 * Turning a minister's question into a search plan.
 *
 * The gap this closes is vocabulary: statutes say "civil emergency" where a
 * person says "blackout", and "furnish information" where they say "tell me".
 * One cheap model call translates, and — crucially — the translation is
 * returned to the caller so the page can show it and let the user correct it.
 * The plan is the filter state; there is no hidden second query.
 */

export interface SearchPlan {
  targets: string[];
  instruments: string[];
  terms: string[];
  domain: string[];
}

export interface PowerFilters {
  actor: string;
  modality: "power" | "duty" | "both";
  legislationKind: "all" | "primary" | "secondary";
  directionOnly: boolean;
  withConditionsOnly: boolean;
  limit: number;
}

export const INSTRUMENT_LABELS: Record<string, string> = {
  direct: "Give directions",
  inspect: "Inspect / require information",
  legislate: "Make legislation",
  guide: "Issue guidance",
  appoint: "Appoint",
  establish: "Establish / abolish",
  fund: "Fund",
  authorise: "Licence / consent",
  charge: "Fees & charges",
  enforce: "Enforce",
  adjudicate: "Adjudicate",
  acquire: "Land & property",
  other: "Other",
};

/**
 * "Any minister" is the collective office and the default. The named entries
 * are the offices asked for often enough to be worth one click; picking one
 * narrows to that office alone, which "any minister" deliberately does not do
 * (Secretary of State is held in commission and never split by portfolio).
 */
export const ACTOR_OPTIONS: [string, string][] = [
  ["minister", "Any minister"],
  ["secretary of state", "Secretary of State"],
  ["scottish ministers", "Scottish Ministers"],
  ["welsh ministers", "Welsh Ministers"],
  ["^(the )?(treasury$|chancellor of the exchequer)", "Treasury or Chancellor"],
  ["lord chancellor", "Lord Chancellor"],
  ["attorney general", "Attorney General"],
  ["lord advocate", "Lord Advocate"],
  ["^(the )?departments?($| |,)", "Northern Ireland department"],
  ["any", "Any actor (incl. courts and regulators)"],
];

const REWRITE_PROMPT = `You turn a UK government minister's question into a search plan over a database of \
statutory powers extracted from UK legislation. The user is a minister asking what powers are \
available to them. Return a JSON object:

{"targets": [<str>, ...], "instruments": [<str>, ...], "terms": [<str>, ...], "domain": [<str>, ...]}

- "targets": bodies, offices, or classes of person the power would be exercised over, as the user \
named them AND as legislation would name them. Include official and statutory names. \
e.g. "NESO" -> ["NESO", "National Energy System Operator", "Independent System Operator and \
Planner", "electricity system operator", "licence holder"]. Empty list if the question names no target.
- "instruments": which of these apply, most relevant first - legislate, direct, guide, appoint, \
establish, fund, authorise, charge, inspect, enforce, adjudicate, acquire. "force X to tell me \
something" is ["direct", "inspect"]. "close down a scheme" is ["establish", "legislate"].
- "terms": the words UK statutes actually use for what the user described. Translate everyday \
language into statutory language: "blackout" -> ["civil emergency", "shortage of electricity", \
"security of supply"]; "tell me" -> ["furnish information", "provide information"]. 4-10 terms.
- "domain": subject-matter words that would appear in the title of a relevant Act, \
e.g. ["electricity", "energy"]. 0-4 words.

Return only the JSON object.`;

const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((v): v is string => typeof v === "string" && v.trim() !== "") : [];

/** Why a question was not translated, so the page can say which. */
export type ReadStatus = "read" | "no_key" | "unavailable";

export interface ReadResult {
  plan: SearchPlan | null;
  status: ReadStatus;
}

/**
 * How long to wait for the translation before giving up and searching on the
 * reader's own words. The call normally returns in 1-2s, but provider routing
 * occasionally lands on one that takes 50s or more, and a page that hangs for
 * a minute is worse than one that searches slightly worse terms.
 */
const REWRITE_TIMEOUT_MS = 15_000;

/**
 * Ask the model to read the question. Never throws and never hangs: on any
 * failure the caller falls back to the raw words, and the status says whether
 * that was because no key is configured or because the call did not come back.
 */
export async function planFromQuestion(question: string, apiKey: string | undefined): Promise<ReadResult> {
  if (apiKey === undefined || apiKey === "") {
    return { plan: null, status: "no_key" };
  }
  try {
    const startedAt = Date.now();
    const response = await fetch("https://openrouter.ai/api/v1/chat/completions", {
      method: "POST",
      headers: { authorization: `Bearer ${apiKey}`, "content-type": "application/json" },
      signal: AbortSignal.timeout(REWRITE_TIMEOUT_MS),
      body: JSON.stringify({
        model: "deepseek/deepseek-v4-flash-0731",
        messages: [
          { role: "system", content: REWRITE_PROMPT },
          { role: "user", content: question },
        ],
        response_format: { type: "json_object" },
        temperature: 0,
        // Reasoning tokens are ~90% of this model's output when left on, for
        // no benefit on an extraction task.
        reasoning: { enabled: false },
        // Latency here is dominated by which provider the request lands on:
        // the same call measured 1.3s and 50s minutes apart. Sorting by
        // throughput keeps it in the low seconds.
        provider: { sort: "throughput" },
        max_tokens: 800,
      }),
    });
    const elapsedMs = Date.now() - startedAt;
    if (elapsedMs > 3_000) {
      console.warn(`powers rewrite: slow provider, ${elapsedMs}ms`);
    }
    if (!response.ok) {
      console.error(`powers rewrite: HTTP ${response.status}`);
      return { plan: null, status: "unavailable" };
    }
    const payload = (await response.json()) as { choices?: { message?: { content?: string } }[] };
    const content = payload.choices?.[0]?.message?.content;
    if (content === undefined) {
      console.error("powers rewrite: response had no content");
      return { plan: null, status: "unavailable" };
    }
    const parsed = JSON.parse(content) as Record<string, unknown>;
    return {
      plan: {
        targets: strings(parsed["targets"]),
        instruments: strings(parsed["instruments"]).filter((i) => i in INSTRUMENT_LABELS),
        terms: strings(parsed["terms"]),
        domain: strings(parsed["domain"]),
      },
      status: "read",
    };
  } catch (error) {
    // Includes the timeout: AbortSignal.timeout throws TimeoutError here.
    console.error(`powers rewrite failed: ${error instanceof Error ? error.name : String(error)}`);
    return { plan: null, status: "unavailable" };
  }
}

/** Fall back to the user's own words when the model is unavailable or switched off. */
export function planFromQuestionText(question: string): SearchPlan {
  return { targets: [], instruments: [], terms: [question.trim()].filter(Boolean), domain: [] };
}

/**
 * Read a plan straight out of the URL. Edited chips post back as repeated
 * params, so an edited search is a plain GET that survives refresh, sharing,
 * and the back button — the plan is addressable state, not hidden in a session.
 */
export function planFromParams(params: URLSearchParams): SearchPlan {
  return {
    targets: params.getAll("target").filter((v) => v.trim() !== ""),
    instruments: params.getAll("instrument").filter((v) => v in INSTRUMENT_LABELS),
    terms: params.getAll("term").filter((v) => v.trim() !== ""),
    domain: params.getAll("domain").filter((v) => v.trim() !== ""),
  };
}

export function filtersFromParams(params: URLSearchParams): PowerFilters {
  const actor = params.get("actor") ?? "minister";
  const modality = params.get("modality");
  const kind = params.get("legislation_kind");
  return {
    actor: ACTOR_OPTIONS.some(([value]) => value === actor) ? actor : "minister",
    modality: modality === "duty" || modality === "both" ? modality : "power",
    legislationKind: kind === "primary" || kind === "secondary" ? kind : "all",
    directionOnly: params.get("direction_only") === "on",
    withConditionsOnly: params.get("with_conditions_only") === "on",
    limit: 20,
  };
}

export function planIsEmpty(plan: SearchPlan): boolean {
  return (
    plan.targets.length === 0 &&
    plan.instruments.length === 0 &&
    plan.terms.length === 0 &&
    plan.domain.length === 0
  );
}

/** Rebuild the query string for a search, so every state has a shareable URL. */
export function powersUrl(question: string, plan: SearchPlan, filters: PowerFilters): string {
  const params = new URLSearchParams();
  if (question.trim() !== "") {
    params.set("q", question.trim());
  }
  for (const target of plan.targets) params.append("target", target);
  for (const instrument of plan.instruments) params.append("instrument", instrument);
  for (const term of plan.terms) params.append("term", term);
  for (const domain of plan.domain) params.append("domain", domain);
  params.set("actor", filters.actor);
  params.set("modality", filters.modality);
  params.set("legislation_kind", filters.legislationKind);
  if (filters.directionOnly) params.set("direction_only", "on");
  if (filters.withConditionsOnly) params.set("with_conditions_only", "on");
  return `/powers?${params.toString()}`;
}
