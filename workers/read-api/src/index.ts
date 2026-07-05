/** Read-only legislation API on Cloudflare Workers (port of git_legislation_api). */

import { Hono } from "hono";
import { cors } from "hono/cors";
import { createSql } from "./db";
import { PostgresRepository } from "./repository";
import { LEGISLATION_TYPE_CODES, type Repository } from "./types";

export interface Env {
  HYPERDRIVE: Hyperdrive;
  BUCKET: R2Bucket;
  CORS_ORIGINS?: string;
}

interface AppOptions {
  /** Override repository construction (used by tests). */
  repository?: (env: Env) => Repository;
}

type Variables = { repository: Repository };

export function createApp(options: AppOptions = {}): Hono<{ Bindings: Env; Variables: Variables }> {
  const app = new Hono<{ Bindings: Env; Variables: Variables }>();

  app.use("*", async (c, next) => {
    const origins = (c.env.CORS_ORIGINS ?? "").split(",").map((o) => o.trim()).filter(Boolean);
    if (origins.length === 0) {
      return next();
    }
    return cors({ origin: origins, allowMethods: ["GET", "OPTIONS"] })(c, next);
  });

  app.use("*", async (c, next) => {
    if (options.repository !== undefined) {
      c.set("repository", options.repository(c.env));
      return next();
    }
    const sql = createSql(c.env.HYPERDRIVE.connectionString);
    c.set("repository", new PostgresRepository(sql));
    try {
      await next();
    } finally {
      c.executionCtx.waitUntil(sql.end({ timeout: 5 }));
    }
  });

  app.get("/healthz", (c) => c.json({ status: "ok" }));

  app.get("/corpus/summary", async (c) => {
    return c.json({ items: await c.get("repository").summarizeDocuments() });
  });

  app.get("/documents", async (c) => {
    const query = c.req.query();
    const legislationType = query["legislation_type"] ?? null;
    if (legislationType !== null && !LEGISLATION_TYPE_CODES.has(legislationType)) {
      return c.json({ detail: `Unknown legislation_type: ${legislationType}` }, 422);
    }
    const year = parseIntParam(query["year"]);
    const limit = parseIntParam(query["limit"]) ?? 50;
    const offset = parseIntParam(query["offset"]) ?? 0;
    if (year === undefined || limit === undefined || offset === undefined) {
      return c.json({ detail: "year, limit, and offset must be integers" }, 422);
    }
    if (limit < 1 || limit > 500 || offset < 0) {
      return c.json({ detail: "limit must be 1-500 and offset >= 0" }, 422);
    }
    const metadataOnly = parseBoolParam(query["metadata_only"]);
    if (metadataOnly === undefined) {
      return c.json({ detail: "metadata_only must be a boolean" }, 422);
    }
    const sort = query["sort"] ?? "default";
    if (sort !== "default" && sort !== "newest") {
      return c.json({ detail: "sort must be default or newest" }, 422);
    }
    const items = await c.get("repository").listDocuments({
      legislationType,
      year,
      number: query["number"] ?? null,
      status: query["status"] ?? null,
      extent: query["extent"] ?? null,
      metadataOnly,
      q: query["q"] ?? null,
      limit,
      offset,
      sort,
    });
    return c.json({ items, limit, offset });
  });

  // Document paths contain slashes (ukpga/2026/14), so match the whole tail
  // and peel known suffixes off the end, mirroring FastAPI's `{path:path}`
  // routes with fixed suffixes.
  app.get("/documents/*", async (c) => {
    const tail = cleanPathId(c.req.path.slice("/documents/".length));
    const repository = c.get("repository");

    if (tail.endsWith("/versions/latest")) {
      const documentId = cleanPathId(tail.slice(0, -"/versions/latest".length));
      const document = await repository.getDocument(documentId);
      const latest = document?.["latest_version"] ?? null;
      if (latest === null) {
        return c.json({ detail: "Latest version not found" }, 404);
      }
      return c.json(latest);
    }
    if (tail.endsWith("/versions")) {
      const documentId = cleanPathId(tail.slice(0, -"/versions".length));
      return c.json({ items: await repository.listVersions(documentId) });
    }
    const document = await repository.getDocument(tail);
    if (document === null) {
      return c.json({ detail: "Document not found" }, 404);
    }
    return c.json(document);
  });

  app.get("/files/:id/content", async (c) => {
    const fileId = parseIntParam(c.req.param("id"));
    if (fileId === undefined || fileId === null) {
      return c.json({ detail: "file id must be an integer" }, 422);
    }
    const fileRecord = await c.get("repository").getFile(fileId);
    return serveObject(c.env.BUCKET, fileRecord, "File content not found");
  });

  // Version ids contain colons and slashes; peel suffixes like above.
  app.get("/versions/*", async (c) => {
    const tail = cleanPathId(c.req.path.slice("/versions/".length));
    const repository = c.get("repository");

    if (tail.endsWith("/provisions")) {
      const versionId = cleanPathId(tail.slice(0, -"/provisions".length));
      return c.json({ items: await repository.listProvisions(versionId) });
    }
    const provisionsIndex = tail.lastIndexOf("/provisions/");
    if (provisionsIndex !== -1) {
      const versionId = cleanPathId(tail.slice(0, provisionsIndex));
      const anchor = tail.slice(provisionsIndex + "/provisions/".length);
      const provision = await repository.getProvision(versionId, anchor);
      if (provision === null) {
        return c.json({ detail: "Provision not found" }, 404);
      }
      return c.json(provision);
    }
    if (tail.endsWith("/files")) {
      const versionId = cleanPathId(tail.slice(0, -"/files".length));
      return c.json({ items: await repository.listFiles(versionId) });
    }
    if (tail.endsWith("/content")) {
      const versionId = cleanPathId(tail.slice(0, -"/content".length));
      const kind = c.req.query("kind") ?? "markdown";
      if (kind !== "markdown" && kind !== "clml_xml") {
        return c.json({ detail: "kind must be markdown or clml_xml" }, 422);
      }
      const fileRecord = await repository.getCanonicalFile(versionId, kind);
      return serveObject(c.env.BUCKET, fileRecord, "Canonical content not found");
    }
    const version = await repository.getVersion(tail);
    if (version === null) {
      return c.json({ detail: "Version not found" }, 404);
    }
    return c.json(version);
  });

  return app;
}

async function serveObject(
  bucket: R2Bucket,
  fileRecord: Record<string, unknown> | null,
  missingDetail: string,
): Promise<Response> {
  const objectKey = fileRecord?.["object_key"];
  if (typeof objectKey !== "string" || objectKey === "") {
    return Response.json({ detail: missingDetail }, { status: 404 });
  }
  const object = await bucket.get(objectKey);
  if (object === null) {
    return Response.json({ detail: "Content object not found" }, { status: 404 });
  }
  const sha256 = String(fileRecord?.["object_sha256"] ?? fileRecord?.["sha256"] ?? "");
  const contentType = String(fileRecord?.["content_type"] ?? "application/octet-stream");
  return new Response(object.body, {
    headers: {
      "Content-Type": contentType,
      "Content-Length": String(object.size),
      ...(sha256 ? { ETag: `"${sha256}"` } : {}),
    },
  });
}

function cleanPathId(value: string): string {
  return value.replace(/^\/+|\/+$/g, "");
}

function parseIntParam(value: string | undefined): number | null | undefined {
  if (value === undefined || value === "") {
    return null;
  }
  const parsed = Number(value);
  return Number.isInteger(parsed) ? parsed : undefined;
}

function parseBoolParam(value: string | undefined): boolean | null | undefined {
  if (value === undefined || value === "") {
    return null;
  }
  const normalized = value.toLowerCase();
  if (["true", "1", "yes", "on"].includes(normalized)) {
    return true;
  }
  if (["false", "0", "no", "off"].includes(normalized)) {
    return false;
  }
  return undefined;
}

const app = createApp();
export default app;
