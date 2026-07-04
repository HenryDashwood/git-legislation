import { describe, expect, it } from "vitest";
import { pgTimestampToIso } from "../src/db";

describe("pgTimestampToIso", () => {
  it("converts postgres timestamptz text to ISO with microseconds intact", () => {
    expect(pgTimestampToIso("2026-06-28 18:59:41.973264+00")).toBe("2026-06-28T18:59:41.973264Z");
    expect(pgTimestampToIso("2026-05-29 22:14:57.261271+00:00")).toBe("2026-05-29T22:14:57.261271Z");
    expect(pgTimestampToIso("2026-05-05 12:00:00+00")).toBe("2026-05-05T12:00:00Z");
  });

  it("leaves non-UTC offsets alone apart from the T separator", () => {
    expect(pgTimestampToIso("2026-06-28 18:59:41+01")).toBe("2026-06-28T18:59:41+01");
  });
});
