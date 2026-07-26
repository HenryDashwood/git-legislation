import { describe, expect, it } from "vitest";
import { attachEffects, computeProvisionDiff } from "../src/diff";

const provision = (number: string, markdown: string, type = "section") => ({
  ordinal: 0,
  provision_type: type,
  number,
  heading: `${number} Heading`,
  anchor: `${number}-heading`,
  markdown,
});

describe("computeProvisionDiff", () => {
  it("marks identical provision sets unchanged", () => {
    const provisions = [provision("1", "text one"), provision("2", "text two")];
    const diff = computeProvisionDiff(provisions, provisions);
    expect(diff.summary).toEqual({ added: 0, removed: 0, changed: 0, unchanged: 2 });
  });

  it("detects amended text as changed", () => {
    const diff = computeProvisionDiff([provision("1", "old text")], [provision("1", "new text")]);
    expect(diff.summary["changed"]).toBe(1);
    expect(diff.entries[0]).toMatchObject({
      status: "changed",
      from_markdown: "old text",
      to_markdown: "new text",
    });
  });

  it("interleaves removed provisions at their original position", () => {
    const from = [provision("1", "a"), provision("2", "b"), provision("3", "c")];
    const to = [provision("1", "a"), provision("3", "c")];
    const diff = computeProvisionDiff(from, to);
    expect(diff.entries.map((entry) => [entry.status, entry.number])).toEqual([
      ["unchanged", "1"],
      ["removed", "2"],
      ["unchanged", "3"],
    ]);
  });

  it("treats repeated numbers as distinct occurrences", () => {
    const from = [provision("1", "part one"), provision("1", "part one again")];
    const to = [provision("1", "part one"), provision("1", "part one changed")];
    const diff = computeProvisionDiff(from, to);
    expect(diff.summary).toEqual({ added: 0, removed: 0, changed: 1, unchanged: 1 });
  });

  it("distinguishes schedules from sections with the same number", () => {
    const from = [provision("1", "section text", "section")];
    const to = [provision("1", "section text", "section"), provision("1", "schedule text", "schedule")];
    const diff = computeProvisionDiff(from, to);
    expect(diff.summary).toEqual({ added: 1, removed: 0, changed: 0, unchanged: 1 });
  });
});

  it("does not flag whitespace-only differences as changed", () => {
    const diff = computeProvisionDiff(
      [provision("1", "in subsection (1)(d) , omit the\nreference")],
      [provision("1", "in subsection (1)(d), omit the reference")],
    );
    expect(diff.summary).toEqual({ added: 0, removed: 0, changed: 0, unchanged: 1 });
  });

it("ignores space before a sentence dot but respects omission dots", () => {
  const clean = computeProvisionDiff(
    [provision("1", "the Immigration Act 2016 .")],
    [provision("1", "the Immigration Act 2016.")],
  );
  expect(clean.summary["unchanged"]).toBe(1);

  const omission = computeProvisionDiff(
    [provision("1", "sections 25A . . . apply")],
    [provision("1", "sections 25A. apply")],
  );
  expect(omission.summary["changed"]).toBe(1);
});

describe("attachEffects", () => {
  const changedEntry = { status: "changed", provision_type: "section", number: "24", heading: "24" };
  const unchangedEntry = { status: "unchanged", provision_type: "section", number: "3", heading: "3" };

  it("accepts a postgres array literal as well as a parsed array", () => {
    const literal = attachEffects([{ ...changedEntry }] as never, [
      { id: "e1", affected_section_numbers: "{24}", affected_provision_kinds: "{section}" },
    ]);
    const parsed = attachEffects([{ ...changedEntry }] as never, [
      { id: "e2", affected_section_numbers: ["24"], affected_provision_kinds: ["section"] },
    ]);

    expect(literal.unattached).toHaveLength(0);
    expect(parsed.unattached).toHaveLength(0);
  });

  it("never attaches to an unchanged provision", () => {
    const result = attachEffects([{ ...unchangedEntry }] as never, [
      { id: "e3", affected_section_numbers: ["3"], affected_provision_kinds: ["section"] },
    ]);

    expect(result.unattached.map((e) => e["id"])).toEqual(["e3"]);
  });

  it("does not cross schedules with sections of the same number", () => {
    const result = attachEffects([{ ...changedEntry, provision_type: "schedule" }] as never, [
      { id: "e4", affected_section_numbers: ["24"], affected_provision_kinds: ["section"] },
    ]);

    expect(result.unattached).toHaveLength(1);
  });
});
