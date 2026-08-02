/** HTMX web frontend on Cloudflare Workers (port of web-app/main.py). */

import { Hono } from "hono";
import { ApiError, ReadApiClient, type ApiEnv, type Json } from "./api";
import { LEGISLATION_TYPE_FILTER_KEYS, buildFilters, pageUrl, parseListParams } from "./params";
import { renderMarkdown } from "./markdown";
import { buildTimeline } from "./timeline";
import { DetailPage } from "./pages/detail";
import { ApiDocsPage } from "./pages/api-docs";
import { ChangesetPage } from "./pages/changeset";
import { DiffPage } from "./pages/diff";
import { LandingPage } from "./pages/landing";
import { ContentPartial, FilesPartial, ProvisionsPartial } from "./pages/partials";
import { FEED_PAGE_SIZE, FeedItems, RecentPage } from "./pages/recent";
import { Results, SearchPage } from "./pages/search";

type Variables = { api: ReadApiClient };

export function createApp(options: { api?: (env: ApiEnv) => ReadApiClient } = {}) {
  const app = new Hono<{ Bindings: ApiEnv; Variables: Variables }>();

  app.use("*", async (c, next) => {
    c.set("api", options.api !== undefined ? options.api(c.env) : new ReadApiClient(c.env.API));
    await next();
  });

  app.get("/", (c) => c.redirect("/documents"));

  app.get("/api", (c) => c.html(<ApiDocsPage />));

  app.get("/documents", async (c) => {
    const params = parseListParams(c.req.url);
    const api = c.get("api");

    if (!params.searched) {
      const [summaryItems, recent] = await Promise.all([
        api
          .getCorpusSummary()
          .then((summary) => (summary["items"] ?? []) as Json[])
          .catch(() => null),
        fetchFeedPage(api, 0, 5).then((feed) => feed.documents),
      ]);
      return c.html(<LandingPage timeline={buildTimeline(summaryItems)} recent={recent} />);
    }

    const results = await fetchResults(api, params.apiParams, params.limit, params.offset);
    return c.html(<SearchPage filters={buildFilters(params.apiParams)} results={results} />);
  });

  app.get("/recent", async (c) => {
    const feed = await fetchFeedPage(c.get("api"), 0);
    return c.html(<RecentPage documents={feed.documents} error={feed.error} />);
  });

  // Infinite-scroll continuation: HTMX swaps this in when the sentinel row
  // scrolls into view.
  app.get("/recent/items", async (c) => {
    const offset = Math.max(Number(c.req.query("offset") ?? 0) || 0, 0);
    const feed = await fetchFeedPage(c.get("api"), offset);
    return c.html(<FeedItems documents={feed.documents} offset={offset} error={feed.error} />);
  });

  // HTMX partial used by older clients; kept for parity with the Python app.
  app.get("/documents/results", async (c) => {
    const params = parseListParams(c.req.url);
    const results = await fetchResults(c.get("api"), params.apiParams, params.limit, params.offset);
    return c.html(<Results {...results} />);
  });

  app.get("/diff", async (c) => {
    const fromId = c.req.query("from") ?? "";
    const toId = c.req.query("to") ?? "";
    if (fromId === "" || toId === "") {
      return c.html(<DiffPage document={null} diff={null} error="Pick two versions to compare." />);
    }
    const api = c.get("api");
    try {
      const diff = await api.getDiff(fromId, toId);
      const document = await api
        .getDocument(String(diff["document_id"] ?? ""))
        .catch(() => null);
      return c.html(<DiffPage document={document} diff={diff} error={null} />);
    } catch (error) {
      return c.html(<DiffPage document={null} diff={null} error={String(error)} />);
    }
  });

  app.get("/changesets/*", async (c) => {
    const documentId = decodeURIComponent(c.req.path.slice("/changesets/".length)).replace(
      /^\/+|\/+$/g,
      "",
    );
    try {
      const changeset = await c.get("api").getChangeset(documentId);
      return c.html(<ChangesetPage changeset={changeset} error={null} />);
    } catch (error) {
      return c.html(<ChangesetPage changeset={null} error={String(error)} />);
    }
  });

  app.get("/documents/*", async (c) => {
    const documentPath = decodeURIComponent(c.req.path.slice("/documents/".length)).replace(
      /^\/+|\/+$/g,
      "",
    );
    const api = c.get("api");
    try {
      const document = await api.getDocument(documentPath);
      const versions = ((await api.listVersions(documentPath))["items"] ?? []) as Json[];
      const latest = (document["latest_version"] as Json | null) ?? null;
      const latestId = latest !== null ? String(latest["id"]) : null;
      let files: Json[] = [];
      let markdown = "";
      let contentLabel = "No parsed text";
      if (latestId !== null) {
        files = ((await api.listFiles(latestId))["items"] ?? []) as Json[];
        const preferred = await api.getPreferredMarkdown(latestId);
        markdown = preferred.markdown;
        contentLabel = preferred.label;
      }
      const pdfFile =
        files.find((file) => file["file_kind"] === "pdf" && file["source_url"]) ?? null;
      return c.html(
        <DetailPage
          document={document}
          versions={versions}
          renderedContent={markdown !== "" ? renderMarkdown(markdown) : ""}
          contentLabel={contentLabel}
          pdfFile={pdfFile}
          error={null}
        />,
      );
    } catch (error) {
      return c.html(
        <DetailPage
          document={null}
          versions={[]}
          renderedContent=""
          contentLabel="No parsed text"
          pdfFile={null}
          error={String(error)}
        />,
      );
    }
  });

  app.get("/versions/*", async (c) => {
    const tail = decodeURIComponent(c.req.path.slice("/versions/".length)).replace(/^\/+|\/+$/g, "");
    const api = c.get("api");

    if (tail.endsWith("/provisions")) {
      const versionId = tail.slice(0, -"/provisions".length);
      try {
        const provisions = ((await api.listProvisions(versionId))["items"] ?? []) as Json[];
        return c.html(<ProvisionsPartial versionId={versionId} provisions={provisions} error={null} />);
      } catch (error) {
        return c.html(<ProvisionsPartial versionId={versionId} provisions={[]} error={String(error)} />);
      }
    }
    if (tail.endsWith("/files")) {
      const versionId = tail.slice(0, -"/files".length);
      try {
        const files = ((await api.listFiles(versionId))["items"] ?? []) as Json[];
        return c.html(<FilesPartial versionId={versionId} files={files} error={null} />);
      } catch (error) {
        return c.html(<FilesPartial versionId={versionId} files={[]} error={String(error)} />);
      }
    }
    if (tail.endsWith("/content")) {
      const versionId = tail.slice(0, -"/content".length);
      try {
        const response = await api.getContentResponse(versionId);
        const content = response.ok ? await response.text() : "";
        return c.html(<ContentPartial versionId={versionId} content={content} error={null} />);
      } catch (error) {
        return c.html(<ContentPartial versionId={versionId} content="" error={String(error)} />);
      }
    }
    if (tail.endsWith("/pdf")) {
      const versionId = tail.slice(0, -"/pdf".length);
      return servePdf(c.get("api"), versionId, c.req.raw, c.executionCtx);
    }
    return c.notFound();
  });

  return app;
}

async function fetchFeedPage(api: ReadApiClient, offset: number, limit: number = FEED_PAGE_SIZE) {
  const params = new URLSearchParams({
    sort: "newest",
    limit: String(limit),
    offset: String(offset),
  });
  try {
    const response = await api.listDocuments(params);
    return { documents: (response["items"] ?? []) as Json[], error: null };
  } catch (error) {
    return { documents: [], error: String(error) };
  }
}

async function fetchResults(
  api: ReadApiClient,
  apiParams: URLSearchParams,
  limit: number,
  offset: number,
) {
  try {
    const response = await api.listDocuments(apiParams);
    const documents = (response["items"] ?? []) as Json[];
    return {
      documents,
      offset,
      error: null,
      prevUrl: offset > 0 ? pageUrl(apiParams, limit, Math.max(offset - limit, 0)) : null,
      nextUrl: documents.length === limit ? pageUrl(apiParams, limit, offset + limit) : null,
    };
  } catch (error) {
    return { documents: [], offset, error: String(error), prevUrl: null, nextUrl: null };
  }
}

/**
 * Serve the source PDF: prefer the cached object (via the API's file-content
 * endpoint), fall back to the upstream URL, and cache responses so the PDF
 * viewer's second request never re-fetches (ported from web-app/main.py).
 */
async function servePdf(
  api: ReadApiClient,
  versionId: string,
  request: Request,
  executionCtx: { waitUntil(promise: Promise<unknown>): void },
): Promise<Response> {
  const cache = caches.default;
  const cacheKey = new Request(new URL(request.url).toString());
  const cached = await cache.match(cacheKey);
  if (cached !== undefined) {
    return cached;
  }

  let files: Json[] = [];
  try {
    files = ((await api.listFiles(versionId))["items"] ?? []) as Json[];
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return Response.json({ detail: "PDF source not found" }, { status: 404 });
    }
    throw error;
  }

  const pdfFiles = files.filter((file) => file["file_kind"] === "pdf");

  // Try every candidate until one yields a real PDF: the cached object first,
  // then print-version URLs (/pdfs/...), then dynamically generated ones like
  // {date}/data.pdf, which legislation.gov.uk often answers with 202/404
  // while it renders them.
  const attempts: (() => Promise<Response>)[] = [];
  for (const file of pdfFiles.filter((file) => file["object_key"])) {
    attempts.push(() => api.getFileContentResponse(Number(file["id"])));
  }
  const sourceUrls = [...new Set(pdfFiles.map((file) => file["source_url"]).filter(Boolean))].map(
    String,
  );
  sourceUrls.sort((a, b) => Number(b.includes("/pdfs/")) - Number(a.includes("/pdfs/")));
  for (const url of sourceUrls) {
    attempts.push(() => fetchPossiblyGeneratedPdf(url));
  }
  if (attempts.length === 0) {
    return pdfUnavailable("No PDF is recorded for this version.");
  }

  for (const attempt of attempts) {
    let upstream: Response;
    try {
      upstream = await attempt();
    } catch (error) {
      console.warn(`pdf candidate threw for ${versionId}: ${String(error)}`);
      continue;
    }
    if (upstream.status !== 200) {
      console.warn(`pdf candidate ${upstream.url || "(cached object)"} -> ${upstream.status} for ${versionId}`);
      continue;
    }
    const body = await upstream.arrayBuffer();
    if (!looksLikePdf(body)) {
      console.warn(`pdf candidate ${upstream.url || "(cached object)"} not a PDF for ${versionId}`);
      continue;
    }
    const response = new Response(body, {
      headers: {
        "Content-Type": "application/pdf",
        "Content-Length": String(body.byteLength),
        "Content-Disposition": 'inline; filename="source.pdf"',
        "Cache-Control": "public, max-age=3600",
      },
    });
    executionCtx.waitUntil(cache.put(cacheKey, response.clone()));
    return response;
  }
  return pdfUnavailable(
    "legislation.gov.uk does not serve this PDF to our proxy - it is generated on demand and only offered directly to browsers.",
    sourceUrls[0],
  );
}

/**
 * legislation.gov.uk generates many PDFs on demand, answering 202 while the
 * render runs (a few seconds). Wait it out rather than giving up. It also
 * answers 404 to requests without a User-Agent, and Workers' fetch sends
 * none by default.
 */
async function fetchPossiblyGeneratedPdf(url: string): Promise<Response> {
  const headers = { "User-Agent": "git-legislation/0.1" };
  let response = await fetch(url, { headers });
  for (let retry = 0; retry < 3 && response.status === 202; retry += 1) {
    await new Promise((resolve) => setTimeout(resolve, 2000));
    response = await fetch(url, { headers });
  }
  return response;
}

function looksLikePdf(body: ArrayBuffer): boolean {
  const head = new TextDecoder().decode(body.slice(0, 8));
  return head.trimStart().startsWith("%PDF");
}

/** Rendered inside the reader's iframe, so return readable HTML, not JSON. */
function pdfUnavailable(message: string, sourceUrl?: string): Response {
  const link =
    sourceUrl !== undefined
      ? `<p><a href="${sourceUrl}" target="_blank" rel="noopener">Open the PDF on legislation.gov.uk</a> (it may take a few seconds to generate)</p>`
      : "";
  return new Response(
    `<!doctype html><html><body style="font-family: Georgia, serif; background: #f7f3ea; color: #1a1712; padding: 2rem;">
      <p>${message}</p>${link}
    </body></html>`,
    { status: 404, headers: { "Content-Type": "text/html; charset=utf-8" } },
  );
}

export { LEGISLATION_TYPE_FILTER_KEYS };

const app = createApp();
export default app;
