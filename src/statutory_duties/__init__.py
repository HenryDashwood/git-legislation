"""Load the Statutory Powers & Duties dataset (research.legislation.gov.uk CSVs).

The release is a folder of CSVs, one set per legislation type, sharing a single
19-column header. A duty whose actor matches several recognised bodies appears
as several otherwise-identical rows (only actorIsAlias/body_uri vary), so the
loader stages the raw rows and lets Postgres collapse them: first row per
duty_uri wins for the duty itself, and every distinct (body, kind) pairing
lands in duty_actor_matches.
"""

import csv
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import psycopg

LEGISLATION_URI_PREFIX = "http://www.legislation.gov.uk/id/"

# Modality arrives dirty in a handful of rows ("Missing", "power and duty",
# "duty|power"); everything else is a clean power/duty split.
MODALITY_BY_RAW_VALUE = {
    "power": "power",
    "duty": "duty",
    "power and duty": "both",
    "duty|power": "both",
    "power|duty": "both",
}

PROVISION_NUMBER_PATTERN = re.compile(r"^\d+[A-Za-z]*$")

CSV_COLUMNS = (
    "dutyTempId",
    "duty_uri",
    "enactment",
    "enactmentTitle",
    "enactmentYear",
    "enactmentType",
    "enactmentNum",
    "section",
    "subsection",
    "actor",
    "actorIsBody",
    "actorIsAlias",
    "actorDefinition",
    "body_uri",
    "modality",
    "action",
    "condition",
    "inference",
    "priority",
)

STAGING_COLUMNS = (
    "duty_uri",
    "source_temp_id",
    "enactment_uri",
    "document_id",
    "enactment_type",
    "enactment_title",
    "enactment_year",
    "enactment_number",
    "section_uri",
    "section_path",
    "provision_kind",
    "provision_number",
    "subsections",
    "actor",
    "actor_is_body",
    "actor_is_alias",
    "actor_definition",
    "body_uri",
    "modality",
    "action",
    "condition",
    "inference",
    "priority",
    "source_file",
)


@dataclass
class DutiesIngestReport:
    files: int = 0
    rows: int = 0
    duties: int = 0
    actor_matches: int = 0
    unlinked_documents: int = 0
    failures: list[str] = field(default_factory=list)


def document_id_from_enactment_uri(enactment_uri: str) -> str | None:
    """'http://www.legislation.gov.uk/id/ukpga/Vict/52-53/39' -> 'ukpga/Vict/52-53/39'."""
    if not enactment_uri.startswith(LEGISLATION_URI_PREFIX):
        return None
    tail = enactment_uri[len(LEGISLATION_URI_PREFIX) :].strip("/")
    return tail or None


def section_path_from_uris(section_uri: str, enactment_uri: str) -> str:
    """The section URI relative to its enactment: 'schedule/2/paragraph/5'."""
    prefix = enactment_uri.rstrip("/") + "/"
    if section_uri.startswith(prefix):
        return section_uri[len(prefix) :].strip("/")
    # A few section URIs sit under a different id root than the enactment
    # column; fall back to stripping the generic prefix so the path still
    # starts at the type segment rather than being lost entirely.
    if section_uri.startswith(LEGISLATION_URI_PREFIX):
        return section_uri[len(LEGISLATION_URI_PREFIX) :].strip("/")
    return section_uri


def provision_kind_and_number(section_path: str) -> tuple[str | None, str | None]:
    """Best-effort top-level provision reference for joining to provisions.number.

    'section/28D' -> ('section', '28D'); 'schedule/2/paragraph/5' ->
    ('schedule', '2'); 'schedule/paragraph/3' -> ('schedule', None) because the
    second segment names structure, not a number.
    """
    segments = [segment for segment in section_path.split("/") if segment]
    if not segments:
        return None, None
    kind = segments[0].lower()
    if len(segments) < 2:
        return kind, None
    number = segments[1]
    if not PROVISION_NUMBER_PATTERN.match(number):
        return kind, None
    return kind, number


def normalize_modality(raw: str) -> str:
    return MODALITY_BY_RAW_VALUE.get(raw.strip().lower(), "unknown")


def normalize_enum(raw: str, allowed: frozenset[str]) -> str | None:
    value = raw.strip().lower()
    return value if value in allowed else None


INFERENCE_VALUES = frozenset({"explicit", "implicit"})
PRIORITY_VALUES = frozenset({"primary", "secondary"})


def staging_row_from_csv_row(row: dict[str, str], source_file: str) -> tuple:
    enactment_uri = row["enactment"].strip()
    section_uri = row["section"].strip()
    section_path = section_path_from_uris(section_uri, enactment_uri)
    provision_kind, provision_number = provision_kind_and_number(section_path)
    document_id = document_id_from_enactment_uri(enactment_uri)
    # The CSV's enactmentType mixes short codes with spelled-out labels
    # ("ScottishAct" alongside asp); the URI's type segment is authoritative.
    enactment_type = document_id.split("/", 1)[0] if document_id else row["enactmentType"].strip()
    subsections = [part for part in row["subsection"].split("|") if part] or None
    return (
        row["duty_uri"].strip(),
        int(row["dutyTempId"]) if row["dutyTempId"].strip() else None,
        enactment_uri,
        document_id,
        enactment_type,
        row["enactmentTitle"],
        row["enactmentYear"].strip() or None,
        row["enactmentNum"].strip() or None,
        section_uri,
        section_path,
        provision_kind,
        provision_number,
        subsections,
        row["actor"],
        row["actorIsBody"].strip() or None,
        row["actorIsAlias"].strip() or None,
        row["actorDefinition"] or None,
        row["body_uri"].strip() or None,
        normalize_modality(row["modality"]),
        row["action"],
        row["condition"] or None,
        normalize_enum(row["inference"], INFERENCE_VALUES),
        normalize_enum(row["priority"], PRIORITY_VALUES),
        source_file,
    )


def iter_dataset_files(dataset_dir: Path) -> list[Path]:
    return sorted(dataset_dir.glob("*.csv"))


def load_duties_csvs(
    connection: psycopg.Connection,
    csv_paths: Iterable[Path],
    dataset_date: str,
    log=lambda message: None,
) -> DutiesIngestReport:
    """Stage every CSV row, then collapse into duties + duty_actor_matches.

    Idempotent per duty_uri: re-running skips duties already present, so a
    partial load can be resumed by running again.
    """
    report = DutiesIngestReport()
    csv.field_size_limit(10**8)
    with connection.cursor() as cursor:
        column_defs = ", ".join(
            f"{column} text[]" if column == "subsections" else f"{column} text" for column in STAGING_COLUMNS
        )
        cursor.execute(f"create temp table duties_staging ({column_defs}) on commit drop")
        copy_sql = f"copy duties_staging ({', '.join(STAGING_COLUMNS)}) from stdin"
        for path in csv_paths:
            with open(path, encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                missing = set(CSV_COLUMNS) - set(reader.fieldnames or [])
                if missing:
                    report.failures.append(f"{path.name}: missing columns {sorted(missing)}")
                    continue
                with cursor.copy(copy_sql) as copy:
                    for row in reader:
                        copy.write_row(staging_row_from_csv_row(row, path.name))
                        report.rows += 1
            report.files += 1
            log(f"staged {path.name} ({report.rows} rows so far)")

        cursor.execute(
            """
            insert into duties.duties (
                duty_uri, source_temp_id, enactment_uri, document_id,
                enactment_type, enactment_title, enactment_year, enactment_number,
                section_uri, section_path, provision_kind, provision_number,
                subsections, actor, actor_definition, modality, action,
                condition, inference, priority, dataset_date, source_file
            )
            select distinct on (duty_uri)
                duty_uri, source_temp_id::bigint, enactment_uri, document_id,
                enactment_type, enactment_title, enactment_year, enactment_number,
                section_uri, section_path, provision_kind, provision_number,
                subsections, actor, actor_definition, modality, action,
                condition, inference, priority, %s::date, source_file
            from duties_staging
            order by duty_uri, source_temp_id::bigint
            on conflict (duty_uri) do nothing
            """,
            (dataset_date,),
        )
        report.duties = cursor.rowcount

        # body_uri accompanies whichever match produced the row; when a row
        # carries both a direct and an alias match, the alias drove the row
        # duplication upstream, so the URI attaches to the alias.
        cursor.execute(
            """
            insert into duties.duty_actor_matches (duty_id, body_name, match_kind, body_uri)
            select duty.id, staged.body_name, staged.match_kind, max(staged.match_body_uri)
            from (
                select duty_uri, actor_is_body as body_name, 'direct' as match_kind,
                       case when actor_is_alias is null then body_uri end as match_body_uri
                from duties_staging
                where actor_is_body is not null
                union all
                select duty_uri, actor_is_alias, 'alias',
                       body_uri
                from duties_staging
                where actor_is_alias is not null
            ) staged
            join duties.duties duty on duty.duty_uri = staged.duty_uri
            group by duty.id, staged.body_name, staged.match_kind
            on conflict (duty_id, body_name, match_kind) do nothing
            """
        )
        report.actor_matches = cursor.rowcount

        cursor.execute(
            """
            select count(*) from duties.duties duty
            left join documents on documents.id = duty.document_id
            where duty.dataset_date = %s and documents.id is null
            """,
            (dataset_date,),
        )
        report.unlinked_documents = cursor.fetchone()[0]
    return report


def render_duties_ingest_report(report: DutiesIngestReport) -> str:
    lines = [
        f"files: {report.files}",
        f"csv rows staged: {report.rows}",
        f"duties inserted: {report.duties}",
        f"actor matches inserted: {report.actor_matches}",
        f"duties without a documents row: {report.unlinked_documents}",
    ]
    lines.extend(f"failure: {failure}" for failure in report.failures)
    return "\n".join(lines)
