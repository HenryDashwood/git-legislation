/** Legislation type codes recognised by the corpus (mirrors git_legislation_api.types). */
export const LEGISLATION_TYPE_CODES = new Set([
  "aep",
  "aosp",
  "aip",
  "apgb",
  "gbppa",
  "gbla",
  "ukpga",
  "ukla",
  "ukppa",
  "apni",
  "ukcm",
  "nisro",
  "uksi",
  "nisi",
  "mnia",
  "nisr",
  "asp",
  "ssi",
  "wsi",
  "nia",
  "mwa",
  "anaw",
  "ukci",
  "asc",
  "ukmo",
]);

export interface DocumentListFilters {
  legislationType: string | null;
  year: number | null;
  number: string | null;
  status: string | null;
  extent: string | null;
  metadataOnly: boolean | null;
  q: string | null;
  limit: number;
  offset: number;
  sort?: "default" | "newest";
}

export type Row = Record<string, unknown>;

/** Read-side repository contract; implemented over Postgres, faked in tests. */
export interface Repository {
  listDocuments(filters: DocumentListFilters): Promise<Row[]>;
  summarizeDocuments(): Promise<Row[]>;
  getDocument(documentId: string): Promise<Row | null>;
  listVersions(documentId: string): Promise<Row[]>;
  getVersion(versionId: string): Promise<Row | null>;
  listProvisions(versionId: string): Promise<Row[]>;
  listProvisionTexts(versionId: string): Promise<Row[]>;
  getProvision(versionId: string, anchor: string): Promise<Row | null>;
  listFiles(versionId: string): Promise<Row[]>;
  getCanonicalFile(versionId: string, fileKind: string): Promise<Row | null>;
  getFile(fileId: number): Promise<Row | null>;
}
