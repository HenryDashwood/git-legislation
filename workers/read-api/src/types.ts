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

export interface EffectFilters {
  documentId: string;
  /** "affected" = changes to this document; "affecting" = changes it made. */
  direction: "affected" | "affecting";
  /** Restrict to effects in force after this date (exclusive). */
  inForceAfter?: string | null;
  /** Restrict to effects in force on or before this date (inclusive). */
  inForceThrough?: string | null;
  textualOnly?: boolean;
  limit?: number;
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
  /** Effects recorded against a document, optionally bounded to an in-force window. */
  listEffects(filters: EffectFilters): Promise<Row[]>;
  /** One group per affected document for everything an instrument changed. */
  summarizeChangeset(affectingDocumentId: string): Promise<Row[]>;
  getProvision(versionId: string, anchor: string): Promise<Row | null>;
  listFiles(versionId: string): Promise<Row[]>;
  getCanonicalFile(versionId: string, fileKind: string): Promise<Row | null>;
  getFile(fileId: number): Promise<Row | null>;
  /** Ranked statutory powers matching a search plan. */
  searchPowers(plan: PowerSearchPlan): Promise<Row[]>;
}

/**
 * A search over statutory powers. The plan is produced by the web app (from a
 * plain-English question, or straight from the filter controls) and applied
 * here verbatim: this service does no query understanding of its own.
 */
export interface PowerSearchPlan {
  /** Bodies or classes the power is exercised over, as legislation might name them. */
  targets: string[];
  /** Instrument facets from power_enrichments.instrument. */
  instruments: string[];
  /** Statutory wording to match against the action text. */
  terms: string[];
  /** Subject-matter words expected in the enactment title. */
  domain: string[];
  /** Restrict to powers held by a minister (or a named one). */
  actor: string | null;
  modality: "power" | "duty" | "both";
  extent: string | null;
  legislationKind: "all" | "primary" | "secondary";
  directionOnly: boolean;
  withConditionsOnly: boolean;
  limit: number;
}

export const POWER_INSTRUMENTS = new Set([
  "legislate",
  "direct",
  "guide",
  "appoint",
  "establish",
  "fund",
  "authorise",
  "charge",
  "inspect",
  "enforce",
  "adjudicate",
  "acquire",
  "other",
]);

/**
 * Actors treated as "a minister" for the ministerial filter.
 *
 * The first version of this was a five-minute regex covering Secretary of
 * State, the Treasury, the Lord Chancellor and the devolved ministers. It
 * silently excluded 3,489 powers held by people who plainly are ministers -
 * including the Attorney General's power to refer an unduly lenient sentence
 * (s.36 Criminal Justice Act 1988) and every power of the Chancellor of the
 * Exchequer. A search that hides whole offices without saying so is worse
 * than one that returns too much, so this list is now explicit and reasoned.
 *
 * Included, and why:
 *  - Secretary of State, in general or by portfolio: the office is held in
 *    commission, so it is never split by department.
 *  - "Minister", "the Ministers", "appropriate/relevant Minister", "Minister
 *    of the Crown": the generic drafting forms.
 *  - The Treasury: a ministerial department; its powers are exercised by
 *    Treasury ministers. Likewise the Chancellor of the Exchequer.
 *  - Law Officers - Attorney General, Solicitor General, Advocate General,
 *    Lord Advocate, Counsel General: government ministers, and the reason
 *    this list was rewritten.
 *  - Prime Minister, Minister for the Civil Service (the same person),
 *    Minister for the Cabinet Office, Chancellor of the Duchy of Lancaster.
 *  - Devolved: Scottish and Welsh Ministers, First Minister, First Minister
 *    and deputy First Minister.
 *  - Northern Ireland departments. NI drafting confers powers on "the
 *    Department" rather than on a named minister, and the department acts
 *    through its minister; excluding them would blank out most NI powers.
 *  - The Privy Council, and "Her/His Majesty in Council". Formally an Order
 *    in Council is made by the Sovereign in Council, but ministers advise and
 *    in substance these are ministerial powers, so a minister asking what
 *    they can do needs them. Included at Henry's direction (2026-08-11).
 *
 * Deliberately excluded, and why:
 *  - Attorney General for Northern Ireland: since the 2010 devolution of
 *    justice the office is independent of the NI Executive, not a minister.
 *    The anchored pattern below matches only the bare "Attorney General".
 *  - Judge Advocate General, judge advocate, the courts: judicial offices.
 *  - Commissioners of Customs and Excise / Inland Revenue, HMRC: a
 *    non-ministerial department is not a minister.
 *  - The Sovereign acting alone ("Her Majesty", "His Majesty", 1,721
 *    powers). Unlike an Order in Council this is not one mechanism: it spans
 *    prerogative acts taken on advice, but also the Crown acting as a private
 *    landowner (applying to cancel a caution against first registration).
 *    Sweeping it in would import powers no minister holds. Worth revisiting
 *    as a separate class if the prerogative matters to the product.
 *  - "Governor in Council": the executive of an overseas territory, advised
 *    by its own council, not a UK minister.
 *  - Delegates - "person authorised by the Secretary of State", "officer of
 *    the Secretary of State". Anchoring every alternative at the start of
 *    the string is what keeps these out: the minister does not hold the
 *    power, the delegate does.
 */
export const MINISTERIAL_ACTOR_PATTERN = [
  "^(the )?secretary of state",
  "^(the )?ministers?$",
  "^(the )?(appropriate|relevant|other|any|those) ministers?$",
  "^(the )?minister of the crown",
  "^(the )?minister (for|of) ",
  "^(the )?prime minister",
  "^(the )?treasury$",
  "^(the )?lords? commissioners of (his|her) majesty.s treasury",
  "^(the )?chancellor of the (exchequer|duchy of lancaster)",
  "^(the )?lord chancellor",
  "^(the )?attorney general$",
  "^(the )?solicitor general",
  "^(the )?advocate general",
  "^(the )?lord advocate",
  "^(the )?counsel general",
  "^(the )?scottish ministers",
  "^(the )?welsh ministers",
  "^(the )?first minister",
  // Postgres regexes use \\y for a word boundary; \\b is a backspace there,
  // so an earlier "^department\\b" silently matched nothing at all.
  "^(the )?departments?($| |,)",
  "^(a |the )?(northern ireland|government) department",
  "^(the )?privy council",
  "^(her|his) majesty in council",
].join("|");
