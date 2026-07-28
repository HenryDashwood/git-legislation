import { env } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { createApp, type Env } from "../src/index";
import type { DocumentListFilters, EffectFilters, Repository, Row } from "../src/types";

const DOCUMENT: Row = {
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
  created_at: "2026-05-05T12:00:00Z",
  updated_at: "2026-05-05T12:00:00Z",
};

const VERSION: Row = {
  id: "point-in-time:2026-05-05:ukpga/2026/14",
  document_id: "ukpga/2026/14",
  version_kind: "point_in_time",
  snapshot_date: "2026-05-05",
  source_uri: "https://www.legislation.gov.uk/ukpga/2026/14/2026-05-05/data.xml",
  source_object_key: "xml/point-in-time/2026-05-05/ukpga/2026/14/data.xml",
  markdown_object_key: "markdown/point-in-time/2026-05-05/ukpga/2026/14.md",
  word_count: 1234,
  is_metadata_only: false,
  created_at: "2026-05-05T12:00:00Z",
};

const MARKDOWN_FILE: Row = {
  id: 1,
  document_id: "ukpga/2026/14",
  version_id: VERSION["id"],
  file_kind: "markdown",
  source_url: null,
  object_key: "markdown/point-in-time/2026-05-05/ukpga/2026/14.md",
  sha256: "abc123",
  is_canonical: true,
  bucket: "legislation",
  byte_size: 18,
  content_type: "text/markdown",
  object_sha256: "abc123",
  created_at: "2026-05-05T12:00:00Z",
};

const EARLIER_VERSION: Row = {
  ...VERSION,
  id: "point-in-time:2020-01-01:ukpga/2026/14",
  snapshot_date: "2020-01-01",
};

const OTHER_DOCUMENT_VERSION: Row = {
  ...VERSION,
  id: "point-in-time:2026-05-05:ukpga/2026/15",
  document_id: "ukpga/2026/15",
};

class FakeRepository implements Repository {
  calls: Record<string, unknown> = {};

  async listDocuments(filters: DocumentListFilters): Promise<Row[]> {
    this.calls["listDocuments"] = filters;
    return [DOCUMENT];
  }

  async summarizeDocuments(): Promise<Row[]> {
    return [{ legislation_type: "ukpga", document_count: 3600, first_year: 1801, last_year: 2026 }];
  }

  async getDocument(documentId: string): Promise<Row | null> {
    this.calls["getDocument"] = documentId;
    if (documentId !== "ukpga/2026/14") {
      return null;
    }
    return { ...DOCUMENT, latest_version: VERSION };
  }

  async listVersions(documentId: string): Promise<Row[]> {
    this.calls["listVersions"] = documentId;
    return [VERSION];
  }

  async getVersion(versionId: string): Promise<Row | null> {
    if (versionId === VERSION["id"]) {
      return VERSION;
    }
    if (versionId === EARLIER_VERSION["id"]) {
      return EARLIER_VERSION;
    }
    if (versionId === OTHER_DOCUMENT_VERSION["id"]) {
      return OTHER_DOCUMENT_VERSION;
    }
    return null;
  }

  async listProvisions(versionId: string): Promise<Row[]> {
    this.calls["listProvisions"] = versionId;
    return [{ id: `${versionId}:provision:1`, ordinal: 1, anchor: "1-limit", heading: "Limit" }];
  }

  async listProvisionTexts(versionId: string): Promise<Row[]> {
    this.calls["listProvisionTexts"] = versionId;
    if (versionId === EARLIER_VERSION["id"]) {
      return [
        { ordinal: 1, provision_type: "section", number: "1", heading: "1 Limit", anchor: "1-limit", markdown: "## 1 Limit\n\nThe limit is £10 billion." },
        { ordinal: 2, provision_type: "section", number: "2", heading: "2 Repealed later", anchor: "2-repealed", markdown: "## 2 Repealed later\n\nGone soon." },
      ];
    }
    return [
      { ordinal: 1, provision_type: "section", number: "1", heading: "1 Limit", anchor: "1-limit", markdown: "## 1 Limit\n\nThe limit is £20 billion." },
      { ordinal: 2, provision_type: "section", number: "3", heading: "3 Brand new", anchor: "3-brand-new", markdown: "## 3 Brand new\n\nNewly inserted." },
    ];
  }

  async listEffects(filters: EffectFilters): Promise<Row[]> {
    this.calls["listEffects"] = filters;
    return [
      {
        id: "key-abc",
        effect_type: "words substituted",
        textual_kind: "T",
        applied: true,
        prospective: false,
        in_force_date: "2026-03-01",
        affecting_document_id: "ukpga/2025/31",
        affecting_title: "Border Security, Asylum and Immigration Act 2025",
        affecting_provisions: "s. 21(9)(b)",
        affected_section_numbers: ["1"],
        affected_provision_kinds: ["section"],
      },
      {
        id: "key-unattached",
        effect_type: "words omitted",
        textual_kind: "T",
        applied: true,
        prospective: false,
        in_force_date: "2026-04-01",
        affecting_document_id: "ukpga/2025/31",
        affected_section_numbers: ["99"],
        affected_provision_kinds: ["section"],
      },
    ];
  }

  async summarizeChangeset(affectingDocumentId: string): Promise<Row[]> {
    this.calls["summarizeChangeset"] = affectingDocumentId;
    if (affectingDocumentId !== "ukpga/2025/31") {
      return [];
    }
    return [
      {
        affected_document_id: "ukpga/2026/14",
        affected_title: "Industry and Exports (Financial Assistance) Act 2026",
        effect_count: 3,
        textual_count: 2,
        applied_count: 3,
        prospective_count: 0,
        in_corpus: true,
      },
    ];
  }

  async getProvision(versionId: string, anchor: string): Promise<Row | null> {
    this.calls["getProvision"] = { versionId, anchor };
    if (anchor !== "1-limit") {
      return null;
    }
    return { id: `${versionId}:provision:1`, anchor, markdown: "## 1 Limit", plain_text: "1 Limit" };
  }

  async listFiles(versionId: string): Promise<Row[]> {
    this.calls["listFiles"] = versionId;
    return [MARKDOWN_FILE];
  }

  async getCanonicalFile(versionId: string, fileKind: string): Promise<Row | null> {
    this.calls["getCanonicalFile"] = { versionId, fileKind };
    return fileKind === "markdown" ? MARKDOWN_FILE : null;
  }

  async getFile(fileId: number): Promise<Row | null> {
    this.calls["getFile"] = fileId;
    return fileId === 1 ? MARKDOWN_FILE : null;
  }
}

function appWith(repository: Repository) {
  return createApp({ repository: () => repository });
}

const testEnv = env as unknown as Env;

describe("read api worker", () => {
  it("serves healthz without touching the database", async () => {
    const response = await appWith(new FakeRepository()).request("/healthz", {}, testEnv);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: "ok" });
  });

  it("lists documents with parsed filters", async () => {
    const repository = new FakeRepository();
    const response = await appWith(repository).request(
      "/documents?legislation_type=ukpga&year=2026&metadata_only=false&q=exports&limit=25&offset=50",
      {},
      testEnv,
    );
    expect(response.status).toBe(200);
    const body = (await response.json()) as Record<string, unknown>;
    expect(body["limit"]).toBe(25);
    expect(body["offset"]).toBe(50);
    expect(repository.calls["listDocuments"]).toEqual({
      legislationType: "ukpga",
      year: 2026,
      number: null,
      status: null,
      extent: null,
      metadataOnly: false,
      q: "exports",
      limit: 25,
      offset: 50,
      sort: "default",
    });
  });

  it("rejects unknown legislation types", async () => {
    const response = await appWith(new FakeRepository()).request(
      "/documents?legislation_type=bogus",
      {},
      testEnv,
    );
    expect(response.status).toBe(422);
  });

  it("returns corpus summary items", async () => {
    const response = await appWith(new FakeRepository()).request("/corpus/summary", {}, testEnv);
    const body = (await response.json()) as { items: Row[] };
    expect(body.items[0]?.["document_count"]).toBe(3600);
  });

  it("returns a document with nested latest version for slash paths", async () => {
    const response = await appWith(new FakeRepository()).request(
      "/documents/ukpga/2026/14",
      {},
      testEnv,
    );
    expect(response.status).toBe(200);
    const body = (await response.json()) as Record<string, unknown>;
    expect((body["latest_version"] as Row)["word_count"]).toBe(1234);
  });

  it("routes versions and versions/latest suffixes", async () => {
    const repository = new FakeRepository();
    const app = appWith(repository);

    const versions = await app.request("/documents/ukpga/2026/14/versions", {}, testEnv);
    expect(versions.status).toBe(200);
    expect(repository.calls["listVersions"]).toBe("ukpga/2026/14");

    const latest = await app.request("/documents/ukpga/2026/14/versions/latest", {}, testEnv);
    expect(latest.status).toBe(200);
    expect(((await latest.json()) as Row)["id"]).toBe(VERSION["id"]);
  });

  it("routes colon-and-slash version ids to provisions, files, and summary", async () => {
    const repository = new FakeRepository();
    const app = appWith(repository);
    const versionId = "point-in-time:2026-05-05:ukpga/2026/14";

    const provisions = await app.request(`/versions/${versionId}/provisions`, {}, testEnv);
    expect(provisions.status).toBe(200);
    expect(repository.calls["listProvisions"]).toBe(versionId);

    const provision = await app.request(`/versions/${versionId}/provisions/1-limit`, {}, testEnv);
    expect(provision.status).toBe(200);
    expect(repository.calls["getProvision"]).toEqual({ versionId, anchor: "1-limit" });

    const files = await app.request(`/versions/${versionId}/files`, {}, testEnv);
    expect(files.status).toBe(200);
    expect(repository.calls["listFiles"]).toBe(versionId);

    const summary = await app.request(`/versions/${versionId}`, {}, testEnv);
    expect(summary.status).toBe(200);
    expect(((await summary.json()) as Row)["word_count"]).toBe(1234);
  });

  it("serves canonical markdown content from the R2 bucket", async () => {
    await testEnv.BUCKET.put(
      "markdown/point-in-time/2026-05-05/ukpga/2026/14.md",
      "# Industry and Exports\n",
    );
    const response = await appWith(new FakeRepository()).request(
      "/versions/point-in-time:2026-05-05:ukpga/2026/14/content",
      {},
      testEnv,
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("text/markdown");
    expect(response.headers.get("etag")).toBe('"abc123"');
    expect(await response.text()).toBe("# Industry and Exports\n");
  });

  it("serves file content by id and 404s when the object is missing", async () => {
    await testEnv.BUCKET.put(
      "markdown/point-in-time/2026-05-05/ukpga/2026/14.md",
      "# Industry and Exports\n",
    );
    const app = appWith(new FakeRepository());

    const found = await app.request("/files/1/content", {}, testEnv);
    expect(found.status).toBe(200);

    class MissingObjectRepository extends FakeRepository {
      override async getFile(fileId: number): Promise<Row | null> {
        const record = await super.getFile(fileId);
        return record === null ? null : { ...record, object_key: "markdown/does-not-exist.md" };
      }
    }
    const missing = await appWith(new MissingObjectRepository()).request(
      "/files/1/content",
      {},
      testEnv,
    );
    expect(missing.status).toBe(404);
  });

  it("404s unknown documents and versions", async () => {
    const app = appWith(new FakeRepository());
    expect((await app.request("/documents/ukpga/1999/1", {}, testEnv)).status).toBe(404);
    expect((await app.request("/versions/enacted:nope", {}, testEnv)).status).toBe(404);
  });
});

  it("passes sort=newest through to the repository and rejects unknown sorts", async () => {
    const repository = new FakeRepository();
    const app = appWith(repository);

    const ok = await app.request("/documents?sort=newest&limit=50", {}, testEnv);
    expect(ok.status).toBe(200);
    expect((repository.calls["listDocuments"] as { sort?: string }).sort).toBe("newest");

    const bad = await app.request("/documents?sort=oldest", {}, testEnv);
    expect(bad.status).toBe(422);
  });

describe("diff endpoint", () => {
  const fromId = "point-in-time:2020-01-01:ukpga/2026/14";
  const toId = "point-in-time:2026-05-05:ukpga/2026/14";

  it("aligns provisions and classifies changes", async () => {
    const response = await appWith(new FakeRepository()).request(
      `/diff?from=${encodeURIComponent(fromId)}&to=${encodeURIComponent(toId)}`,
      {},
      testEnv,
    );
    expect(response.status).toBe(200);
    const body = (await response.json()) as Record<string, unknown>;
    expect(body["document_id"]).toBe("ukpga/2026/14");
    expect(body["summary"]).toEqual({ added: 1, removed: 1, changed: 1, unchanged: 0 });
    const entries = body["entries"] as Record<string, unknown>[];
    expect(entries.map((entry) => entry["status"])).toEqual(["changed", "removed", "added"]);
    const changed = entries[0]!;
    expect(changed["from_markdown"]).toContain("£10 billion");
    expect(changed["to_markdown"]).toContain("£20 billion");
  });

  it("rejects versions from different documents", async () => {
    const response = await appWith(new FakeRepository()).request(
      `/diff?from=${encodeURIComponent(toId)}&to=${encodeURIComponent(
        "point-in-time:2026-05-05:ukpga/2026/15",
      )}`,
      {},
      testEnv,
    );
    expect(response.status).toBe(422);
  });

  it("returns 404 for unknown versions", async () => {
    const response = await appWith(new FakeRepository()).request(
      `/diff?from=nope&to=${encodeURIComponent(toId)}`,
      {},
      testEnv,
    );
    expect(response.status).toBe(404);
  });

  it("requires both version ids", async () => {
    const response = await appWith(new FakeRepository()).request("/diff?from=x", {}, testEnv);
    expect(response.status).toBe(422);
  });
});

describe("percent-encoded path ids", () => {
  it("resolves a version id whose colons are encoded", async () => {
    const repository = new FakeRepository();
    const encoded = encodeURIComponent(String(VERSION["id"]));
    const response = await appWith(repository).request(`/versions/${encoded}/provisions`, {}, testEnv);

    expect(response.status).toBe(200);
    expect(repository.calls["listProvisions"]).toBe(VERSION["id"]);
  });

  it("resolves a document id whose slashes are encoded", async () => {
    const repository = new FakeRepository();
    const response = await appWith(repository).request("/documents/ukpga%2F2026%2F14", {}, testEnv);

    expect(response.status).toBe(200);
    expect(repository.calls["getDocument"]).toBe("ukpga/2026/14");
  });

  it("does not throw on a malformed escape sequence", async () => {
    const response = await appWith(new FakeRepository()).request("/documents/ukpga%2", {}, testEnv);

    expect(response.status).toBe(404);
  });
});

describe("effects on diffs and changesets", () => {
  const fromId = "point-in-time:2020-01-01:ukpga/2026/14";
  const toId = "point-in-time:2026-05-05:ukpga/2026/14";

  it("attaches an effect only to a provision that really changed", async () => {
    const response = await appWith(new FakeRepository()).request(
      `/diff?from=${encodeURIComponent(fromId)}&to=${encodeURIComponent(toId)}`,
      {},
      testEnv,
    );
    const body = (await response.json()) as Record<string, unknown>;
    const entries = body["entries"] as Record<string, unknown>[];
    const changed = entries.find((entry) => entry["status"] === "changed")!;
    const attached = changed["effects"] as Record<string, unknown>[];

    expect(attached).toHaveLength(1);
    expect(attached[0]?.["id"]).toBe("key-abc");
  });

  it("returns effects it could not pin separately rather than guessing", async () => {
    const response = await appWith(new FakeRepository()).request(
      `/diff?from=${encodeURIComponent(fromId)}&to=${encodeURIComponent(toId)}`,
      {},
      testEnv,
    );
    const body = (await response.json()) as Record<string, unknown>;
    const unattached = body["unattached_effects"] as Record<string, unknown>[];

    expect(unattached.map((effect) => effect["id"])).toEqual(["key-unattached"]);
  });

  it("bounds the effect window to the versions being compared", async () => {
    const repository = new FakeRepository();
    await appWith(repository).request(
      `/diff?from=${encodeURIComponent(fromId)}&to=${encodeURIComponent(toId)}`,
      {},
      testEnv,
    );
    expect(repository.calls["listEffects"]).toMatchObject({
      documentId: "ukpga/2026/14",
      direction: "affected",
      inForceAfter: "2020-01-01",
      inForceThrough: "2026-05-05",
      textualOnly: true,
    });
  });

  it("summarises a changeset by affected document", async () => {
    const response = await appWith(new FakeRepository()).request(
      "/changesets/ukpga/2025/31",
      {},
      testEnv,
    );
    expect(response.status).toBe(200);
    const body = (await response.json()) as Record<string, unknown>;
    expect(body["summary"]).toMatchObject({ effects: 3, textual: 2, documents_affected: 1 });
  });

  it("404s a changeset with no recorded effects", async () => {
    const response = await appWith(new FakeRepository()).request("/changesets/ukpga/1900/1", {}, testEnv);
    expect(response.status).toBe(404);
  });

  it("lists effects for a document", async () => {
    const repository = new FakeRepository();
    const response = await appWith(repository).request(
      "/documents/ukpga/2026/14/effects?direction=affecting",
      {},
      testEnv,
    );
    expect(response.status).toBe(200);
    expect(repository.calls["listEffects"]).toMatchObject({ direction: "affecting" });
  });
});

describe("compressed object serving", () => {
  it("decompresses a gzipped object so consumers see plain content", async () => {
    const plain = "# Heading\n\nBody text.";
    const gzipped = new Response(
      new Blob([plain]).stream().pipeThrough(new CompressionStream("gzip")),
    );
    const stored = await gzipped.arrayBuffer();

    class GzRepository extends FakeRepository {
      override async getCanonicalFile(): Promise<Row | null> {
        return {
          ...MARKDOWN_FILE,
          object_key: "markdown/point-in-time/2026-05-05/ukpga/2026/14.md.gz",
          content_type: "text/markdown",
        };
      }
    }

    const bucket = {
      get: async () => ({ body: new Blob([stored]).stream(), size: stored.byteLength }),
    };
    const app = createApp({ repository: () => new GzRepository() });
    const response = await app.request(
      `/versions/${encodeURIComponent(String(VERSION["id"]))}/content?kind=markdown`,
      {},
      { ...testEnv, BUCKET: bucket } as unknown as Env,
    );

    expect(response.status).toBe(200);
    expect(await response.text()).toBe(plain);
  });
});
