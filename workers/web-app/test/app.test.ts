import { describe, expect, it } from "vitest";
import { createApp } from "../src/index";
import type { ApiEnv } from "../src/api";

const DOCUMENT = {
  id: "ukpga/2026/14",
  legislation_type: "ukpga",
  year: "2026",
  calendar_year: 2026,
  number: "14",
  title: "Industry and Exports (Financial Assistance) Act 2026",
  document_uri: "https://www.legislation.gov.uk/ukpga/2026/14",
  status: "Prospective",
  extent: "E+W+S+N.I.",
  latest_version_id: "point-in-time:2026-05-05:ukpga/2026/14",
};

const VERSION = {
  id: "point-in-time:2026-05-05:ukpga/2026/14",
  document_id: "ukpga/2026/14",
  version_kind: "point_in_time",
  snapshot_date: "2026-05-05",
  word_count: 1234,
  is_metadata_only: false,
};

const FILES = [
  {
    id: 1,
    file_kind: "markdown",
    object_key: "markdown/point-in-time/2026-05-05/ukpga/2026/14.md",
    source_url: null,
    is_canonical: true,
    content_type: "text/markdown",
  },
  {
    id: 2,
    file_kind: "pdf",
    object_key: null,
    source_url: "https://www.legislation.gov.uk/ukpga/2026/14/data.pdf",
    is_canonical: false,
  },
];

/** Routes API paths to canned responses, standing in for the service binding. */
function fakeApiFetcher(overrides: Record<string, () => Response> = {}): Fetcher {
  const routes: Record<string, () => Response> = {
    "/corpus/summary": () =>
      Response.json({
        items: [
          { legislation_type: "ukpga", document_count: 3600, first_year: 1801, last_year: 2026 },
          { legislation_type: "wsi", document_count: 8123, first_year: 1999, last_year: 2026 },
        ],
      }),
    "/documents": () => Response.json({ items: [DOCUMENT], limit: 50, offset: 0 }),
    "/documents/ukpga/2026/14": () =>
      Response.json({ ...DOCUMENT, latest_version: VERSION }),
    "/documents/ukpga/2026/14/versions": () => Response.json({ items: [VERSION] }),
    [`/versions/${VERSION.id}/files`]: () => Response.json({ items: FILES }),
    [`/versions/${VERSION.id}/provisions`]: () =>
      Response.json({
        items: [{ ordinal: 1, number: "1", heading: "Limit on assistance", anchor: "1-limit" }],
      }),
    [`/versions/${VERSION.id}/content`]: () =>
      new Response("---\ntitle: x\n---\n\n# Industry and Exports\n\nBody text.\n", {
        headers: { "Content-Type": "text/markdown" },
      }),
    ...overrides,
  };
  return {
    fetch: async (input: RequestInfo | URL) => {
      const url = new URL(input instanceof Request ? input.url : String(input));
      const handler = routes[url.pathname];
      if (handler === undefined) {
        return Response.json({ detail: "not found" }, { status: 404 });
      }
      return handler();
    },
  } as unknown as Fetcher;
}

function envWith(fetcher: Fetcher): ApiEnv {
  return { API: fetcher, ASSETS: fetcher } as ApiEnv;
}

const executionCtx = {
  waitUntil: () => undefined,
  passThroughOnException: () => undefined,
} as unknown as ExecutionContext;

describe("web app worker", () => {
  it("redirects the root to /documents", async () => {
    const app = createApp();
    const response = await app.request("/", {}, envWith(fakeApiFetcher()), executionCtx);
    expect(response.status).toBe(302);
    expect(response.headers.get("location")).toBe("/documents");
  });

  it("renders the landing page with corpus counts and no document fetch", async () => {
    const app = createApp();
    const response = await app.request("/documents", {}, envWith(fakeApiFetcher()), executionCtx);
    const html = await response.text();
    expect(response.status).toBe(200);
    expect(html).toContain("statute book");
    expect(html).toContain("11,723 documents");
    expect(html).toContain("UK Public General Acts");
    expect(html).toContain("Eight centuries of law");
    expect(html).not.toContain("Industry and Exports");
  });

  it("renders the landing page even when the summary endpoint fails", async () => {
    const app = createApp();
    const fetcher = fakeApiFetcher({
      "/corpus/summary": () => Response.json({ detail: "boom" }, { status: 500 }),
    });
    const response = await app.request("/documents", {}, envWith(fetcher), executionCtx);
    expect(response.status).toBe(200);
    expect(await response.text()).toContain("Eight centuries of law");
  });

  it("treats empty form fields as absent and renders search results", async () => {
    const app = createApp();
    const response = await app.request(
      "/documents?q=exports&legislation_type=&year=&metadata_only=",
      {},
      envWith(fakeApiFetcher()),
      executionCtx,
    );
    const html = await response.text();
    expect(response.status).toBe(200);
    expect(html).toContain("Search results");
    expect(html).toContain("Industry and Exports");
    expect(html).toContain("2026 c. 14");
  });

  it("renders pagination when a full page comes back", async () => {
    const app = createApp();
    const fetcher = fakeApiFetcher({
      "/documents": () =>
        Response.json({ items: [DOCUMENT], limit: 1, offset: 1 }),
    });
    const response = await app.request(
      "/documents?legislation_type=ukpga&limit=1&offset=1",
      {},
      envWith(fetcher),
      executionCtx,
    );
    const html = await response.text();
    expect(html).toContain("/documents?legislation_type=ukpga&amp;limit=1");
    expect(html).toContain("offset=2");
    expect(html).toContain("Previous page");
    expect(html).toContain("Next page");
  });

  it("renders the document detail reader with markdown and HTMX controls", async () => {
    const app = createApp();
    const response = await app.request(
      "/documents/ukpga/2026/14",
      {},
      envWith(fakeApiFetcher()),
      executionCtx,
    );
    const html = await response.text();
    expect(response.status).toBe(200);
    expect(html).toContain("<h1>Industry and Exports (Financial Assistance) Act 2026</h1>");
    expect(html).toContain("Canonical CLML text");
    expect(html).toContain("Body text.");
    expect(html).not.toContain("title: x");
    expect(html).toContain(`hx-get="/versions/${VERSION.id}/provisions"`);
    expect(html).toContain('id="source-toggle"');
    expect(html).toContain("Hide PDF");
    expect(html).toContain(`src="/versions/${VERSION.id}/pdf"`);
  });

  it("serves the provisions partial for HTMX", async () => {
    const app = createApp();
    const response = await app.request(
      `/versions/${VERSION.id}/provisions`,
      {},
      envWith(fakeApiFetcher()),
      executionCtx,
    );
    const html = await response.text();
    expect(response.status).toBe(200);
    expect(html).toContain("Limit on assistance");
    expect(html).not.toContain("<html");
  });

  it("proxies the source PDF and caches it", async () => {
    let upstreamCalls = 0;
    const app = createApp();
    const fetcher = fakeApiFetcher();
    const realFetch = globalThis.fetch;
    globalThis.fetch = (async () => {
      upstreamCalls += 1;
      return new Response("%PDF-1.4 example", { headers: { "Content-Type": "application/pdf" } });
    }) as typeof fetch;
    try {
      const first = await app.request(
        `https://example.com/versions/${VERSION.id}/pdf`,
        {},
        envWith(fetcher),
        executionCtx,
      );
      expect(first.status).toBe(200);
      expect(first.headers.get("content-type")).toBe("application/pdf");
      expect(await first.text()).toBe("%PDF-1.4 example");
      expect(upstreamCalls).toBe(1);
    } finally {
      globalThis.fetch = realFetch;
    }
  });
});

describe("pdf proxy fallbacks", () => {
  const MULTI_PDF_FILES = [
    { id: 5, file_kind: "pdf", object_key: null, source_url: "https://www.legislation.gov.uk/asc/2026/3/2026-05-05/data.pdf" },
    { id: 6, file_kind: "pdf", object_key: null, source_url: "https://www.legislation.gov.uk/asc/2026/3/pdfs/asc_20260003_en.pdf" },
  ];

  it("falls through failing candidates and prefers /pdfs/ urls", async () => {
    const fetched: string[] = [];
    const app = createApp();
    const fetcher = fakeApiFetcher({
      [`/versions/${VERSION.id}/files`]: () => Response.json({ items: MULTI_PDF_FILES }),
    });
    const realFetch = globalThis.fetch;
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = input instanceof Request ? input.url : String(input);
      fetched.push(url);
      if (url.includes("/pdfs/")) {
        return new Response("%PDF-1.7 real", { headers: { "Content-Type": "application/pdf" } });
      }
      return new Response("try later", { status: 202 });
    }) as typeof fetch;
    try {
      const response = await app.request(
        `https://example.com/versions/${VERSION.id}/pdf?v=fallback`,
        {},
        envWith(fetcher),
        executionCtx,
      );
      expect(response.status).toBe(200);
      expect(await response.text()).toBe("%PDF-1.7 real");
      expect(fetched[0]).toContain("/pdfs/");
    } finally {
      globalThis.fetch = realFetch;
    }
  });

  it("returns a readable html notice when no candidate yields a pdf", async () => {
    const app = createApp();
    const fetcher = fakeApiFetcher({
      [`/versions/${VERSION.id}/files`]: () => Response.json({ items: MULTI_PDF_FILES }),
    });
    const realFetch = globalThis.fetch;
    globalThis.fetch = (async () =>
      new Response("<html>not a pdf</html>", { status: 200 })) as typeof fetch;
    try {
      const response = await app.request(
        `https://example.com/versions/${VERSION.id}/pdf?v=allfail`,
        {},
        envWith(fetcher),
        executionCtx,
      );
      expect(response.status).toBe(404);
      expect(response.headers.get("content-type")).toContain("text/html");
      expect(await response.text()).toContain("legislation.gov.uk");
    } finally {
      globalThis.fetch = realFetch;
    }
  });
});

  it("waits out 202 pdf-generation responses", async () => {
    let calls = 0;
    const app = createApp();
    const fetcher = fakeApiFetcher();
    const realFetch = globalThis.fetch;
    globalThis.fetch = (async () => {
      calls += 1;
      if (calls === 1) {
        return new Response("generating, please wait", { status: 202 });
      }
      return new Response("%PDF-1.5 generated", { headers: { "Content-Type": "application/pdf" } });
    }) as typeof fetch;
    try {
      const response = await app.request(
        `https://example.com/versions/${VERSION.id}/pdf?v=generated`,
        {},
        envWith(fetcher),
        executionCtx,
      );
      expect(response.status).toBe(200);
      expect(await response.text()).toBe("%PDF-1.5 generated");
      expect(calls).toBe(2);
    } finally {
      globalThis.fetch = realFetch;
    }
  }, 10000);
