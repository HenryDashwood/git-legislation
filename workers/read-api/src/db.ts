/** Postgres client tuned for Workers + response-shape parity with the Python API. */

import postgres from "postgres";
import type { Sql } from "postgres";

/**
 * Postgres renders timestamptz as "2026-06-28 18:59:41.973264+00"; the Python
 * API (Pydantic) emitted "2026-06-28T18:59:41.973264Z". Convert the text form
 * directly so microsecond precision survives (a JS Date would truncate to ms).
 */
export function pgTimestampToIso(value: string): string {
  return value.replace(" ", "T").replace(/\+00(:00)?$/, "Z");
}

export function createSql(connectionString: string): Sql {
  return postgres(connectionString, {
    max: 5,
    fetch_types: false,
    prepare: false,
    types: {
      // Keep `date` columns as plain "YYYY-MM-DD" strings.
      date: {
        to: 1082,
        from: [1082],
        serialize: (value: string) => value,
        parse: (value: string) => value,
      },
      // timestamp (1114) and timestamptz (1184) as ISO strings.
      timestamp: {
        to: 1184,
        from: [1114, 1184],
        serialize: (value: string) => value,
        parse: pgTimestampToIso,
      },
    },
  });
}
