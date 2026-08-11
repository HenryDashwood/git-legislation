import { describe, expect, it } from "vitest";
import { pgTimestampToIso } from "../src/db";
import { buildTsquery, toPgTextArray } from "../src/repository";
import { MINISTERIAL_ACTOR_PATTERN } from "../src/types";

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

describe("toPgTextArray", () => {
  it("builds a Postgres array literal", () => {
    expect(toPgTextArray(["NESO", "licence holder"])).toBe('{"NESO","licence holder"}');
    expect(toPgTextArray([])).toBe("{}");
  });

  it("escapes quotes and backslashes so a target cannot break out of the literal", () => {
    expect(toPgTextArray(['say "hi"'])).toBe('{"say \\"hi\\""}');
    expect(toPgTextArray(["back\\slash"])).toBe('{"back\\\\slash"}');
  });
});

describe("MINISTERIAL_ACTOR_PATTERN", () => {
  // Postgres regexes are case-insensitive here via ~*, so mirror that.
  const matches = (actor: string) => new RegExp(MINISTERIAL_ACTOR_PATTERN, "i").test(actor);

  it("includes the offices that are ministers", () => {
    for (const actor of [
      "Secretary of State",
      "Secretary of State for Defence",
      "Minister",
      "the Ministers",
      "appropriate Minister",
      "Minister of the Crown",
      "Minister for the Civil Service",
      "Treasury",
      "Chancellor of the Exchequer",
      "Lord Chancellor",
      "Prime Minister",
      "Scottish Ministers",
      "Welsh Ministers",
      "First Minister",
      "Department",
      "Department of Justice",
      "Northern Ireland department",
    ]) {
      expect(matches(actor), actor).toBe(true);
    }
  });

  it("includes Orders in Council: formally the Sovereign's, in substance ministerial", () => {
    for (const actor of ["Privy Council", "the Privy Council", "Her Majesty in Council", "His Majesty in Council"]) {
      expect(matches(actor), actor).toBe(true);
    }
  });

  it("still excludes the Sovereign acting alone, which is not one mechanism", () => {
    // "Her Majesty" covers prerogative acts taken on advice but also the
    // Crown as a private landowner, so it is not a ministerial class.
    for (const actor of ["Her Majesty", "His Majesty", "Governor in Council"]) {
      expect(matches(actor), actor).toBe(false);
    }
  });

  it("includes the Law Officers — the omission that hid s.36 Criminal Justice Act 1988", () => {
    for (const actor of ["Attorney General", "Solicitor General", "Lord Advocate", "Advocate General for Scotland"]) {
      expect(matches(actor), actor).toBe(true);
    }
  });

  it("excludes offices that are not ministers", () => {
    for (const actor of [
      "Attorney General for Northern Ireland", // independent of the Executive since 2010
      "Judge Advocate General",
      "judge advocate",
      "Court of Appeal",
      "Director of Public Prosecutions",
      "Commissioners of Inland Revenue",
      "administering authority",
      "chancellor", // a university or diocesan chancellor, not the Exchequer
    ]) {
      expect(matches(actor), actor).toBe(false);
    }
  });

  it("excludes delegates: the minister does not hold a power exercised by their appointee", () => {
    for (const actor of [
      "person authorised by Secretary of State",
      "officer of the Secretary of State",
      "person appointed by Secretary of State",
      "person authorised by Minister",
      "Head of the Department",
      "special advocate",
    ]) {
      expect(matches(actor), actor).toBe(false);
    }
  });
});

describe("buildTsquery", () => {
  it("ANDs the words of a term rather than requiring a phrase", () => {
    // "deprivation of citizenship" must reach "deprive a person of
    // citizenship status" — s.40 British Nationality Act 1981.
    expect(buildTsquery(["deprivation of citizenship"])).toBe("deprivation of citizenship");
    expect(buildTsquery(["civil emergency", "security of supply"])).toBe(
      "civil emergency OR security of supply",
    );
  });

  it("strips websearch operators hiding inside a term", () => {
    // Otherwise "peace order and good government" reparses as an OR/AND
    // expression rather than the words the drafter used.
    expect(buildTsquery(["peace order and good government"])).toBe("peace order good government");
    expect(buildTsquery(['say "this"', "-negated"])).toBe("say this OR negated");
  });

  it("never returns an empty query", () => {
    expect(buildTsquery([])).toBe("power");
    expect(buildTsquery(["  ", "and"])).toBe("power");
  });
});
