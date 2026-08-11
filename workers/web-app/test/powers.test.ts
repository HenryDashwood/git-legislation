import { describe, expect, it } from "vitest";
import {
  filtersFromParams,
  planFromParams,
  planFromQuestionText,
  planIsEmpty,
  powersUrl,
} from "../src/powers";

describe("planFromParams", () => {
  it("reads an edited plan back out of the query string", () => {
    const params = new URLSearchParams(
      "target=NESO&target=licence+holder&instrument=direct&instrument=inspect&term=civil+emergency&domain=electricity",
    );
    expect(planFromParams(params)).toEqual({
      targets: ["NESO", "licence holder"],
      instruments: ["direct", "inspect"],
      terms: ["civil emergency"],
      domain: ["electricity"],
    });
  });

  it("drops blank chips and unknown instruments", () => {
    const params = new URLSearchParams("target=&target=NESO&instrument=direct&instrument=nonsense&term=+");
    const plan = planFromParams(params);
    expect(plan.targets).toEqual(["NESO"]);
    expect(plan.instruments).toEqual(["direct"]);
    expect(plan.terms).toEqual([]);
  });
});

describe("filtersFromParams", () => {
  it("defaults to ministerial powers", () => {
    const filters = filtersFromParams(new URLSearchParams());
    expect(filters.actor).toBe("minister");
    expect(filters.modality).toBe("power");
    expect(filters.legislationKind).toBe("all");
    expect(filters.directionOnly).toBe(false);
  });

  it("reads checkboxes and rejects an unknown actor", () => {
    const filters = filtersFromParams(
      new URLSearchParams("actor=bogus&modality=duty&legislation_kind=primary&direction_only=on"),
    );
    expect(filters.actor).toBe("minister");
    expect(filters.modality).toBe("duty");
    expect(filters.legislationKind).toBe("primary");
    expect(filters.directionOnly).toBe(true);
  });
});

describe("powersUrl", () => {
  it("round-trips a plan through the query string", () => {
    const plan = {
      targets: ["NESO"],
      instruments: ["direct"],
      terms: ["civil emergency"],
      domain: ["electricity"],
    };
    const filters = {
      actor: "minister" as const,
      modality: "power" as const,
      legislationKind: "all" as const,
      directionOnly: true,
      withConditionsOnly: false,
      limit: 20,
    };
    const url = powersUrl("blackout", plan, filters);
    const params = new URLSearchParams(url.split("?")[1]);
    expect(planFromParams(params)).toEqual(plan);
    expect(filtersFromParams(params).directionOnly).toBe(true);
    expect(params.get("q")).toBe("blackout");
    // No re-read marker: a shared link must not spend a model call, and must
    // not silently overwrite chips the sender edited by hand.
    expect(params.get("reread")).toBeNull();
  });
});

describe("planIsEmpty", () => {
  it("is true only when nothing at all is set", () => {
    expect(planIsEmpty({ targets: [], instruments: [], terms: [], domain: [] })).toBe(true);
    expect(planIsEmpty({ targets: [], instruments: [], terms: ["x"], domain: [] })).toBe(false);
  });
});

describe("planFromQuestionText", () => {
  it("falls back to the user's own words when the model is unavailable", () => {
    const plan = planFromQuestionText("  close down a quango  ");
    expect(plan.terms).toEqual(["close down a quango"]);
    expect(plan.targets).toEqual([]);
  });
});
