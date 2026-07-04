/** Query-parameter handling for the document list (ported from web-app/main.py). */

import type { Filters } from "./pages/search";

export const LEGISLATION_TYPE_FILTER_KEYS = [
  "legislation_type",
  "year",
  "number",
  "status",
  "extent",
  "metadata_only",
  "q",
] as const;

export interface ListParams {
  searched: boolean;
  limit: number;
  offset: number;
  /** Filter params with empty values dropped, ready to send to the read API. */
  apiParams: URLSearchParams;
}

/**
 * HTML forms submit every field, so blank values arrive as empty strings.
 * Treat them as absent, mirroring the Python app's middleware.
 */
export function parseListParams(url: string): ListParams {
  const query = new URL(url).searchParams;
  const apiParams = new URLSearchParams();
  let searched = false;
  for (const key of LEGISLATION_TYPE_FILTER_KEYS) {
    const value = query.get(key);
    if (value !== null && value !== "") {
      apiParams.set(key, value);
      searched = true;
    }
  }
  const limit = clampInt(query.get("limit"), 1, 500, 50);
  const offset = Math.max(clampInt(query.get("offset"), 0, Number.MAX_SAFE_INTEGER, 0), 0);
  apiParams.set("limit", String(limit));
  apiParams.set("offset", String(offset));
  return { searched, limit, offset, apiParams };
}

export function buildFilters(apiParams: URLSearchParams): Filters {
  return {
    legislation_type: apiParams.get("legislation_type") ?? "",
    year: apiParams.get("year") ?? "",
    number: apiParams.get("number") ?? "",
    status: apiParams.get("status") ?? "",
    extent: apiParams.get("extent") ?? "",
    metadata_only: apiParams.get("metadata_only") ?? "",
    q: apiParams.get("q") ?? "",
  };
}

export function pageUrl(apiParams: URLSearchParams, limit: number, offset: number): string {
  const params = new URLSearchParams();
  for (const key of LEGISLATION_TYPE_FILTER_KEYS) {
    const value = apiParams.get(key);
    if (value !== null && value !== "") {
      params.set(key, value);
    }
  }
  if (limit !== 50) {
    params.set("limit", String(limit));
  }
  if (offset > 0) {
    params.set("offset", String(offset));
  }
  const query = params.toString();
  return `/documents${query ? `?${query}` : ""}`;
}

function clampInt(value: string | null, min: number, max: number, fallback: number): number {
  if (value === null || value === "") {
    return fallback;
  }
  const parsed = Number(value);
  if (!Number.isInteger(parsed)) {
    return fallback;
  }
  return Math.min(Math.max(parsed, min), max);
}
