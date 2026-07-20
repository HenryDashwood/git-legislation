/** Word-level diff rendering for changed provisions. */

const MAX_TOKENS = 4000;

/**
 * Render an inline word-level diff of two texts as HTML with <del>/<ins>
 * marks. Falls back to stacked old/new blocks when the texts are too large
 * for the quadratic alignment to run comfortably in a Worker.
 */
export function renderWordDiff(fromText: string, toText: string): string {
  const fromTokens = tokenize(fromText);
  const toTokens = tokenize(toText);
  if (fromTokens.length > MAX_TOKENS || toTokens.length > MAX_TOKENS) {
    return `<div class="diff-fallback"><del>${escapeHtml(fromText)}</del><ins>${escapeHtml(toText)}</ins></div>`;
  }

  const ops = diffTokens(fromTokens, toTokens);
  const html: string[] = [];
  for (const op of ops) {
    const text = escapeHtml(op.tokens.join(""));
    if (text === "") {
      continue;
    }
    if (op.kind === "equal") {
      html.push(text);
    } else if (op.kind === "delete") {
      html.push(`<del>${text}</del>`);
    } else {
      html.push(`<ins>${text}</ins>`);
    }
  }
  return html.join("");
}

interface DiffOp {
  kind: "equal" | "delete" | "insert";
  tokens: string[];
}

/** Split into word and whitespace tokens so joins reproduce the input. */
function tokenize(text: string): string[] {
  return text.split(/(\s+)/).filter((token) => token !== "");
}

function diffTokens(fromTokens: string[], toTokens: string[]): DiffOp[] {
  const rows = fromTokens.length + 1;
  const cols = toTokens.length + 1;
  const lengths = new Uint16Array(rows * cols);
  for (let i = fromTokens.length - 1; i >= 0; i -= 1) {
    for (let j = toTokens.length - 1; j >= 0; j -= 1) {
      lengths[i * cols + j] =
        fromTokens[i] === toTokens[j]
          ? 1 + (lengths[(i + 1) * cols + j + 1] ?? 0)
          : Math.max(lengths[(i + 1) * cols + j] ?? 0, lengths[i * cols + j + 1] ?? 0);
    }
  }

  const ops: DiffOp[] = [];
  const push = (kind: DiffOp["kind"], token: string) => {
    const last = ops[ops.length - 1];
    if (last !== undefined && last.kind === kind) {
      last.tokens.push(token);
    } else {
      ops.push({ kind, tokens: [token] });
    }
  };

  let i = 0;
  let j = 0;
  while (i < fromTokens.length && j < toTokens.length) {
    if (fromTokens[i] === toTokens[j]) {
      push("equal", fromTokens[i] ?? "");
      i += 1;
      j += 1;
    } else if ((lengths[(i + 1) * cols + j] ?? 0) >= (lengths[i * cols + j + 1] ?? 0)) {
      push("delete", fromTokens[i] ?? "");
      i += 1;
    } else {
      push("insert", toTokens[j] ?? "");
      j += 1;
    }
  }
  for (; i < fromTokens.length; i += 1) {
    push("delete", fromTokens[i] ?? "");
  }
  for (; j < toTokens.length; j += 1) {
    push("insert", toTokens[j] ?? "");
  }
  return ops;
}

function escapeHtml(text: string): string {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
