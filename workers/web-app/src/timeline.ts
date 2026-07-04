/** Corpus timeline model for the landing page (ported from web-app/main.py). */

import { SERIES_BY_CODE, TIMELINE_GROUPS } from "./legislation";
import type { Json } from "./api";

export interface TimelineRow {
  code: string;
  label: string;
  firstYear: number;
  lastLabel: string;
  countLabel: string | null;
  leftPct: number;
  widthPct: number;
}

export interface Timeline {
  groups: { title: string; slug: string; rows: TimelineRow[] }[];
  ticks: { year: number; leftPct: number }[];
  startYear: number;
  endYear: number;
  totalLabel: string | null;
}

export function buildTimeline(summaryItems: Json[] | null, now: Date = new Date()): Timeline {
  const counts = new Map<string, number>();
  for (const item of summaryItems ?? []) {
    const code = item["legislation_type"];
    const count = item["document_count"];
    if (typeof code === "string" && typeof count === "number") {
      counts.set(code, count);
    }
  }

  const startYear = Math.min(...[...SERIES_BY_CODE.values()].map((series) => series.startYear));
  const endYear = now.getUTCFullYear();
  const totalYears = endYear - startYear;

  let totalDocuments = 0;
  const groups = TIMELINE_GROUPS.map((group) => ({
    title: group.title,
    slug: group.slug,
    rows: group.codes
      .map((code) => SERIES_BY_CODE.get(code))
      .filter((series) => series !== undefined)
      .sort((a, b) => a.startYear - b.startYear)
      .map((series) => {
        const first = series.startYear;
        const last = series.endYear ?? endYear;
        const count = counts.get(series.code);
        totalDocuments += count ?? 0;
        return {
          code: series.code,
          label: series.label,
          firstYear: first,
          lastLabel: series.endYear === null ? "present" : String(series.endYear),
          countLabel: count ? count.toLocaleString("en-GB") : null,
          leftPct: Math.round(((first - startYear) / totalYears) * 10000) / 100,
          widthPct: Math.max(Math.round(((last - first) / totalYears) * 10000) / 100, 0.6),
        };
      }),
  }));

  const ticks = [];
  for (let year = 1300; year < endYear; year += 100) {
    ticks.push({ year, leftPct: Math.round(((year - startYear) / totalYears) * 10000) / 100 });
  }

  return {
    groups,
    ticks,
    startYear,
    endYear,
    totalLabel: totalDocuments > 0 ? totalDocuments.toLocaleString("en-GB") : null,
  };
}
