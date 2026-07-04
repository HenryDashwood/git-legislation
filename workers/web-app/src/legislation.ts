/** Legislation series metadata (ported from git_legislation_api.types and the fetcher module). */

export interface SeriesInfo {
  code: string;
  label: string;
  startYear: number;
  endYear: number | null;
}

export const SERIES: SeriesInfo[] = [
  { code: "aep", label: "Acts of the English Parliament", startYear: 1267, endYear: 1706 },
  { code: "aosp", label: "Acts of the Old Scottish Parliament", startYear: 1424, endYear: 1707 },
  { code: "aip", label: "Acts of the Old Irish Parliament", startYear: 1495, endYear: 1800 },
  { code: "apgb", label: "Acts of the Parliament of Great Britain", startYear: 1707, endYear: 1800 },
  {
    code: "gbppa",
    label: "Private and Personal Acts of the Parliament of Great Britain",
    startYear: 1707,
    endYear: 1800,
  },
  { code: "gbla", label: "Local Acts of the Parliament of Great Britain", startYear: 1797, endYear: 1800 },
  { code: "ukpga", label: "UK Public General Acts", startYear: 1801, endYear: null },
  { code: "ukla", label: "UK Local Acts", startYear: 1801, endYear: null },
  { code: "ukppa", label: "UK Private and Personal Acts", startYear: 1801, endYear: null },
  { code: "apni", label: "Acts of the Northern Ireland Parliament", startYear: 1921, endYear: 1972 },
  { code: "ukcm", label: "UK Church Measures", startYear: 1920, endYear: null },
  { code: "nisro", label: "Northern Ireland Statutory Rules and Orders", startYear: 1922, endYear: null },
  { code: "uksi", label: "UK Statutory Instruments", startYear: 1948, endYear: null },
  { code: "nisi", label: "Northern Ireland Orders in Council", startYear: 1972, endYear: null },
  { code: "mnia", label: "Measures of the Northern Ireland Assembly", startYear: 1974, endYear: 1974 },
  { code: "nisr", label: "Northern Ireland Statutory Rules", startYear: 1991, endYear: null },
  { code: "asp", label: "Acts of the Scottish Parliament", startYear: 1999, endYear: null },
  { code: "ssi", label: "Scottish Statutory Instruments", startYear: 1999, endYear: null },
  { code: "wsi", label: "Wales Statutory Instruments", startYear: 1999, endYear: null },
  { code: "nia", label: "Acts of the Northern Ireland Assembly", startYear: 2000, endYear: null },
  { code: "mwa", label: "Measures of the Welsh Assembly", startYear: 2008, endYear: null },
  { code: "anaw", label: "Acts of the Welsh Assembly", startYear: 2012, endYear: null },
  { code: "ukci", label: "UK Church Instruments", startYear: 2013, endYear: null },
  { code: "asc", label: "Acts of Senedd Cymru", startYear: 2020, endYear: null },
  { code: "ukmo", label: "UK Ministerial Orders", startYear: 2020, endYear: null },
];

export const SERIES_BY_CODE = new Map(SERIES.map((series) => [series.code, series]));

export const TYPE_LABELS: Record<string, string> = Object.fromEntries(
  SERIES.map((series) => [series.code, series.label]),
);

/** Ordered chronologically for the corpus timeline; slugs pick jurisdiction colours. */
export const TIMELINE_GROUPS: { title: string; slug: string; codes: string[] }[] = [
  { title: "Historical parliaments", slug: "historic", codes: ["aep", "aosp", "aip", "apgb", "gbppa", "gbla"] },
  { title: "UK Parliament", slug: "uk", codes: ["ukpga", "ukla", "ukppa", "uksi", "ukmo", "ukcm", "ukci"] },
  { title: "Scotland", slug: "scotland", codes: ["asp", "ssi"] },
  { title: "Wales", slug: "wales", codes: ["asc", "anaw", "mwa", "wsi"] },
  { title: "Northern Ireland", slug: "ni", codes: ["nia", "nisr", "nisi", "apni", "mnia", "nisro"] },
];

/** Acts are cited by chapter ("c. 14"); instruments, rules, and measures by number ("No. 14"). */
export const CHAPTER_CITED_TYPES = new Set(
  SERIES.filter((series) => series.label.includes("Act") || series.label.includes("Personal")).map(
    (series) => series.code,
  ),
);

export function citation(legislationType: string, year: unknown, number: unknown): string {
  const marker = CHAPTER_CITED_TYPES.has(legislationType) ? "c." : "No.";
  return `${year} ${marker} ${number}`;
}

export const STATUS_OPTIONS = ["Prospective", "Revoked", "Repealed", "Current", "Unknown"];

export const METADATA_OPTIONS = [
  { value: "", label: "All records" },
  { value: "false", label: "Full parsed text" },
  { value: "true", label: "Metadata/PDF-backed only" },
];
