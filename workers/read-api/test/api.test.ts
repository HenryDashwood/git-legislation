import { env } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { createApp, type Env } from "../src/index";
import type { DocumentListFilters, Repository, Row } from "../src/types";

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
    return versionId === VERSION["id"] ? VERSION : null;
  }

  async listProvisions(versionId: string): Promise<Row[]> {
    this.calls["listProvisions"] = versionId;
    return [{ id: `${versionId}:provision:1`, ordinal: 1, anchor: "1-limit", heading: "Limit" }];
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
