/** Markdown rendering for statute text (ported from web-app/main.py). */

import MarkdownIt from "markdown-it";

const renderer = new MarkdownIt({ html: false, linkify: false, typographer: false });

export function stripFrontmatter(content: string): string {
  const lines = content.split("\n");
  if (lines.length === 0 || lines[0]?.trim() !== "---") {
    return content;
  }
  for (let index = 1; index < lines.length; index += 1) {
    if (lines[index]?.trim() === "---") {
      return lines
        .slice(index + 1)
        .join("\n")
        .replace(/^\s+/, "");
    }
  }
  return content;
}

export function renderMarkdown(content: string): string {
  return renderer.render(stripFrontmatter(content));
}
