/** Provision-level alignment and diff between two versions of a document. */

import type { Row } from "./types";

export type DiffStatus = "added" | "removed" | "changed" | "unchanged";

export interface DiffEntry {
  status: DiffStatus;
  provision_type: string | null;
  number: string | null;
  /** Jurisdiction for an alternative-extent reading; null for the primary text. */
  extent?: string | null;
  heading: string | null;
  anchor: string | null;
  from_heading?: string | null;
  from_markdown?: string;
  to_markdown?: string;
  /** Effects that explain this change, attached only when the text really differs. */
  effects?: Row[];
}

export interface ProvisionDiff {
  summary: Record<DiffStatus, number>;
  entries: DiffEntry[];
}

/**
 * Attach effects to the diff entries they explain, confirmation-first.
 *
 * An effect is only pinned to a provision when that provision actually changed
 * between the two versions: the amendment register and the revised text do not
 * always agree, and a confident-but-wrong attribution is worse than none. What
 * cannot be pinned is returned separately so the caller can still show it as a
 * recorded amendment without claiming which words it touched.
 */
export function attachEffects(
  entries: DiffEntry[],
  effects: Row[],
): { entries: DiffEntry[]; unattached: Row[] } {
  const changedByKey = new Map<string, DiffEntry[]>();
  for (const entry of entries) {
    if (entry.status === "unchanged" || entry.number === null) {
      continue;
    }
    const key = `${entry.provision_type ?? ""}|${entry.number}`;
    const bucket = changedByKey.get(key);
    if (bucket === undefined) {
      changedByKey.set(key, [entry]);
    } else {
      bucket.push(entry);
    }
  }

  const unattached: Row[] = [];
  for (const effect of effects) {
    const numbers = asStringArray(effect["affected_section_numbers"]);
    const kinds = asStringArray(effect["affected_provision_kinds"]);
    let attached = false;
    for (const number of numbers) {
      for (const kind of kinds.length > 0 ? kinds : [""]) {
        for (const entry of changedByKey.get(`${kind}|${number}`) ?? []) {
          (entry.effects ??= []).push(effect);
          attached = true;
        }
      }
    }
    if (!attached) {
      unattached.push(effect);
    }
  }
  return { entries, unattached };
}

/**
 * Postgres arrays reach us either already parsed or as a literal like "{24,3}"
 * depending on how the driver types an aggregate column, so accept both.
 */
function asStringArray(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === "string");
  }
  if (typeof value === "string" && value.startsWith("{") && value.endsWith("}")) {
    return value
      .slice(1, -1)
      .split(",")
      .map((item) => item.replace(/^"|"$/g, "").trim())
      .filter((item) => item !== "");
  }
  return [];
}

/**
 * Align provisions of two versions and classify each as added, removed,
 * changed, or unchanged.
 *
 * Provisions are matched by type + number (falling back to heading), with an
 * occurrence counter so repeated numbers pair up in document order. Statute
 * provisions essentially never reorder, so alignment walks both sequences
 * monotonically: a match earlier than the current position is treated as a
 * remove + add rather than a move.
 */
export function computeProvisionDiff(fromProvisions: Row[], toProvisions: Row[]): ProvisionDiff {
  const fromKeys = provisionKeys(fromProvisions);
  const toKeys = provisionKeys(toProvisions);
  const fromIndexByKey = new Map<string, number>();
  fromKeys.forEach((key, index) => {
    if (!fromIndexByKey.has(key)) {
      fromIndexByKey.set(key, index);
    }
  });

  // Pair up matching provisions first (monotonic in both sequences), then walk
  // the gaps between pairs emitting removals before additions, the way a
  // reader expects a legal diff to read.
  const pairs: [number, number][] = [];
  let fromCursor = 0;
  toKeys.forEach((key, toIndex) => {
    const fromIndex = fromIndexByKey.get(key);
    if (fromIndex !== undefined && fromIndex >= fromCursor) {
      pairs.push([fromIndex, toIndex]);
      fromCursor = fromIndex + 1;
    }
  });

  const entries: DiffEntry[] = [];
  const emitGap = (fromStart: number, fromEnd: number, toStart: number, toEnd: number) => {
    for (let index = fromStart; index < fromEnd; index += 1) {
      const provision = fromProvisions[index];
      if (provision !== undefined) {
        entries.push({ ...describeProvision(provision), status: "removed", from_markdown: String(provision["markdown"] ?? "") });
      }
    }
    for (let index = toStart; index < toEnd; index += 1) {
      const provision = toProvisions[index];
      if (provision !== undefined) {
        entries.push({ ...describeProvision(provision), status: "added", to_markdown: String(provision["markdown"] ?? "") });
      }
    }
  };

  let previousFrom = 0;
  let previousTo = 0;
  for (const [fromIndex, toIndex] of pairs) {
    emitGap(previousFrom, fromIndex, previousTo, toIndex);
    const fromProvision = fromProvisions[fromIndex];
    const toProvision = toProvisions[toIndex];
    const fromMarkdown = String(fromProvision?.["markdown"] ?? "");
    const toMarkdown = String(toProvision?.["markdown"] ?? "");
    const changed = normalizeForComparison(fromMarkdown) !== normalizeForComparison(toMarkdown);
    const entry: DiffEntry = {
      ...describeProvision(toProvision ?? {}),
      status: changed ? "changed" : "unchanged",
      from_heading: asOptionalString(fromProvision?.["heading"]),
    };
    if (changed) {
      entry.from_markdown = fromMarkdown;
      entry.to_markdown = toMarkdown;
    }
    entries.push(entry);
    previousFrom = fromIndex + 1;
    previousTo = toIndex + 1;
  }
  emitGap(previousFrom, fromProvisions.length, previousTo, toProvisions.length);

  const summary: Record<DiffStatus, number> = { added: 0, removed: 0, changed: 0, unchanged: 0 };
  for (const entry of entries) {
    summary[entry.status] += 1;
  }
  return { summary, entries };
}

/**
 * Whitespace-insensitive comparison guard: point-in-time expressions of the
 * same text have been rendered from both compact and pretty-printed CLML,
 * and residual spacing skew (spaces before punctuation, run length) must not
 * flag a provision as legally changed.
 */
function normalizeForComparison(markdown: string): string {
  return markdown
    .replace(/\s+/g, " ")
    .replace(/ +([,;:)\]])/g, "$1")
    .replace(/(?<![.\s]) +\.(?!\s*\.)/g, ".")
    .trim();
}

function describeProvision(provision: Row): Omit<DiffEntry, "status"> {
  return {
    provision_type: asOptionalString(provision["provision_type"]),
    number: asOptionalString(provision["number"]),
    extent: asOptionalString(provision["extent"]),
    heading: asOptionalString(provision["heading"]),
    anchor: asOptionalString(provision["anchor"]),
  };
}

function provisionKeys(provisions: Row[]): string[] {
  const seen = new Map<string, number>();
  return provisions.map((provision) => {
    // Extent is part of a provision's identity: an Act can carry an E+W and a
    // Scottish reading of the same section, and they must diff against their
    // own counterpart rather than each other.
    const base = `${provision["provision_type"] ?? ""}|${
      provision["number"] ?? provision["heading"] ?? provision["anchor"] ?? ""
    }|${provision["extent"] ?? ""}`;
    const occurrence = seen.get(base) ?? 0;
    seen.set(base, occurrence + 1);
    return `${base}#${occurrence}`;
  });
}

function asOptionalString(value: unknown): string | null {
  return value === null || value === undefined ? null : String(value);
}
