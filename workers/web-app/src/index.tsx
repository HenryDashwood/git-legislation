/** HTMX web frontend on Cloudflare Workers (port of web-app/main.py). */

import { Hono } from "hono";
import { ApiError, ReadApiClient, type ApiEnv, type Json } from "./api";
import { LEGISLATION_TYPE_FILTER_KEYS, buildFilters, pageUrl, parseListParams } from "./params";
import { renderMarkdown } from "./markdown";
import { buildTimeline } from "./timeline";
import { DetailPage } from "./pages/detail";
import { LandingPage } from "./pages/landing";
import { ContentPartial, FilesPartial, ProvisionsPartial } from "./pages/partials";
import { Results, SearchPage } from "./pages/search";

type Variables = { api: ReadApiClient };

export function createApp(options: { api?: (env: ApiEnv) => ReadApiClient } = {}) {
  const app = new Hono<{ Bindings: ApiEnv; Variables: Variables }>();

  app.use("*", async (c, next) => {
    c.set("api", options.api !== undefined ? options.api(c.env) : new ReadApiClient(c.env.API));
    await next();
  });

  app.get("/", (c) => c.redirect("/documents"));

  app.get("/documents", async (c) => {
    const params = parseListParams(c.req.url);
    const api = c.get("api");

    if (!params.searched) {
      let summaryItems: Json[] | null = null;
      try {
        summaryItems = ((await api.getCorpusSummary())["items"] ?? []) as Json[];
      } catch {
        summaryItems = null;
      }
      return c.html(<LandingPage timeline={buildTimeline(summaryItems)} />);
    }

    const results = await fetchResults(api, params.apiParams, params.limit, params.offset);
    return c.html(<SearchPage filters={buildFilters(params.apiParams)} results={results} />);
  });

  // HTMX partial used by older clients; kept for parity with the Python app.
  app.get("/documents/results", async (c) => {
    const params = parseListParams(c.req.url);
    const results = await fetchResults(c.get("api"), params.apiParams, params.limit, params.offset);
    return c.html(<Results {...results} />);
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

  const cachedPdf = files.find((file) => file["file_kind"] === "pdf" && file["object_key"]);
  const sourcePdf = files.find((file) => file["file_kind"] === "pdf" && file["source_url"]);

  let upstream: Response;
  if (cachedPdf !== undefined) {
    upstream = await api.getFileContentResponse(Number(cachedPdf["id"]));
  } else if (sourcePdf !== undefined) {
    upstream = await fetch(String(sourcePdf["source_url"]));
  } else {
    return Response.json({ detail: "PDF source not found" }, { status: 404 });
  }
  if (!upstream.ok) {
    return Response.json({ detail: `PDF fetch failed: ${upstream.status}` }, { status: 502 });
  }

  const body = await upstream.arrayBuffer();
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

export { LEGISLATION_TYPE_FILTER_KEYS };

const app = createApp();
export default app;
