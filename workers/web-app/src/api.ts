/** Read-API client over the service binding (ported from web-app/api_client.py). */

export interface ApiEnv {
  API: Fetcher;
  ASSETS: Fetcher;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export type Json = Record<string, unknown>;

export class ReadApiClient {
  constructor(private readonly api: Fetcher) {}

  private async getJson(path: string): Promise<Json> {
    const response = await this.api.fetch(`https://read-api${path}`);
    if (!response.ok) {
      throw new ApiError(`API request failed: ${response.status} for ${path}`, response.status);
    }
    return (await response.json()) as Json;
  }

  async listDocuments(params: URLSearchParams): Promise<Json> {
    const query = params.toString();
    return this.getJson(`/documents${query ? `?${query}` : ""}`);
  }

  async getCorpusSummary(): Promise<Json> {
    return this.getJson("/corpus/summary");
  }

  async getDocument(documentPath: string): Promise<Json> {
    return this.getJson(`/documents/${documentPath}`);
  }

  async listVersions(documentPath: string): Promise<Json> {
    return this.getJson(`/documents/${documentPath}/versions`);
  }

  async listProvisions(versionId: string): Promise<Json> {
    return this.getJson(`/versions/${versionId}/provisions`);
  }

  async listFiles(versionId: string): Promise<Json> {
    return this.getJson(`/versions/${versionId}/files`);
  }

  async getContentResponse(versionId: string): Promise<Response> {
    return this.api.fetch(`https://read-api/versions/${versionId}/content`);
  }

  async getFileContentResponse(fileId: number): Promise<Response> {
    return this.api.fetch(`https://read-api/files/${fileId}/content`);
  }

  /**
   * Prefer PDF-derived Marker text, then LiteParse text, then canonical CLML
   * markdown (ported from api_client.get_preferred_markdown).
   */
  async getPreferredMarkdown(versionId: string): Promise<{ markdown: string; label: string }> {
    const files = ((await this.listFiles(versionId))["items"] ?? []) as Json[];
    const preferences: [string, string][] = [
      ["markdown/marker/", "PDF-derived Marker text"],
      ["markdown/liteparse/", "PDF-derived LiteParse text"],
    ];
    for (const [prefix, label] of preferences) {
      const file = files.find(
        (item) =>
          item["file_kind"] === "markdown" && String(item["object_key"] ?? "").startsWith(prefix),
      );
      if (file !== undefined) {
        const response = await this.getFileContentResponse(Number(file["id"]));
        if (response.ok) {
          return { markdown: await response.text(), label };
        }
      }
    }
    const canonical = await this.getContentResponse(versionId);
    if (!canonical.ok) {
      return { markdown: "", label: "No parsed text" };
    }
    return { markdown: await canonical.text(), label: "Canonical CLML text" };
  }
}
