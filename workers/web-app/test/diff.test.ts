import { describe, expect, it } from "vitest";
import { renderWordDiff } from "../src/diff";

describe("renderWordDiff", () => {
  it("wraps replaced words in del and ins", () => {
    const html = renderWordDiff("the limit is £10 billion", "the limit is £20 billion");
    expect(html).toBe("the limit is <del>£10</del><ins>£20</ins> billion");
  });

  it("escapes markup in both sides", () => {
    const html = renderWordDiff("a <b> c", "a <i> c");
    expect(html).toContain("&lt;b&gt;");
    expect(html).toContain("&lt;i&gt;");
    expect(html).not.toContain("<b>");
  });

  it("returns plain text unchanged", () => {
    expect(renderWordDiff("same text", "same text")).toBe("same text");
  });

  it("handles pure insertion", () => {
    expect(renderWordDiff("one two", "one extra two")).toBe("one <ins>extra </ins>two");
  });
});
