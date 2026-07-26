"""Persist amendment effects from legislation.gov.uk's Changes to Legislation feeds."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import psycopg

from fetchers.legislationdotgovdotuk import Effect

# Editorial effect types that carry no textual change; kept but flagged so the
# UI can default to showing only effects that alter the words of a provision.
NON_TEXTUAL_EFFECT_TYPES = frozenset(
    {
        "applied",
        "applied (with modifications)",
        "excluded",
        "extended",
        "extended (with modifications)",
        "modified",
        "restricted",
        "specified",
        "power to apply",
        "power to amend",
        "power to modify",
        "power to repeal",
        "power to transfer",
        "referred to",
        "explained",
        "construed as one with",
        "amendment to earlier commencing SI",
        "see",
    }
)


@dataclass
class EffectsIngestReport:
    documents: int = 0
    fetched: int = 0
    stored: int = 0
    provision_refs: int = 0
    unlinked_affected: int = 0
    failures: list[str] = field(default_factory=list)


def textual_kind(effect_type: str) -> str:
    """Classify an effect as textual (T), non-textual (NT), commencement (CO), or unknown (UN).

    Upstream records some effects with an empty Type; those are genuinely
    untyped rather than non-textual, so they get their own kind instead of
    being silently filed as NT.
    """
    normalized = effect_type.strip().lower()
    if not normalized:
        return "UN"
    if "commencement" in normalized or normalized.startswith("in force"):
        return "CO"
    if normalized in NON_TEXTUAL_EFFECT_TYPES:
        return "NT"
    return "T"


def upsert_effects(
    connection: psycopg.Connection[Any],
    effects: Iterable[Effect],
    report: EffectsIngestReport,
) -> None:
    for effect in effects:
        connection.execute(
            """
            insert into effects (
                id, uri, effect_type, textual_kind, applied, requires_applied, prospective,
                in_force_date, in_force_qualification, commencing_document_id, commencement_authority,
                affected_document_id, affected_title, affected_provisions,
                affecting_document_id, affecting_title, affecting_provisions,
                comments, modified, updated_at
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            on conflict (id) do update set
                uri = excluded.uri,
                effect_type = excluded.effect_type,
                textual_kind = excluded.textual_kind,
                applied = excluded.applied,
                requires_applied = excluded.requires_applied,
                prospective = excluded.prospective,
                in_force_date = excluded.in_force_date,
                in_force_qualification = excluded.in_force_qualification,
                commencing_document_id = excluded.commencing_document_id,
                commencement_authority = excluded.commencement_authority,
                affected_document_id = excluded.affected_document_id,
                affected_title = excluded.affected_title,
                affected_provisions = excluded.affected_provisions,
                affecting_document_id = excluded.affecting_document_id,
                affecting_title = excluded.affecting_title,
                affecting_provisions = excluded.affecting_provisions,
                comments = excluded.comments,
                modified = excluded.modified,
                updated_at = now()
            """,
            (
                effect.id,
                effect.uri,
                effect.effect_type,
                textual_kind(effect.effect_type),
                effect.applied,
                effect.requires_applied,
                effect.prospective,
                effect.in_force_date,
                effect.in_force_qualification,
                effect.commencing_document_id,
                effect.commencement_authority,
                effect.affected_document_id,
                effect.affected_title,
                effect.affected_provisions,
                effect.affecting_document_id,
                effect.affecting_title,
                effect.affecting_provisions,
                effect.comments,
                effect.modified,
            ),
        )
        # Provision refs are a full replace: the upstream record is the whole
        # truth for an effect, and refs carry no local state worth preserving.
        connection.execute("delete from effect_provisions where effect_id = %s", (effect.id,))
        for provision in effect.provisions:
            connection.execute(
                """
                insert into effect_provisions (
                    effect_id, side, provision_kind, section_number, ref, uri, label
                ) values (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    effect.id,
                    provision.side,
                    provision.provision_kind,
                    provision.section_number,
                    provision.ref,
                    provision.uri,
                    provision.label,
                ),
            )
            report.provision_refs += 1
        report.stored += 1
        if effect.affected_document_id is None:
            report.unlinked_affected += 1


def record_effects_cursor(
    connection: psycopg.Connection[Any],
    document_id: str,
    effects: list[Effect],
) -> None:
    last_modified = max((effect.modified for effect in effects if effect.modified), default=None)
    connection.execute(
        """
        insert into effects_cursor (document_id, last_modified, effect_count, refreshed_at)
        values (%s, %s, %s, now())
        on conflict (document_id) do update set
            last_modified = excluded.last_modified,
            effect_count = excluded.effect_count,
            refreshed_at = now()
        """,
        (document_id, last_modified, len(effects)),
    )


def render_effects_ingest_report(report: EffectsIngestReport) -> str:
    lines = [
        f"Ingested effects for {report.documents} documents: {report.fetched} fetched, "
        f"{report.stored} stored, {report.provision_refs} provision refs, "
        f"{report.unlinked_affected} against unpublished legislation, {len(report.failures)} failures"
    ]
    lines.extend(f"- {failure}" for failure in report.failures[:20])
    return "\n".join(lines)


def summarize_effect_coverage(
    connection: psycopg.Connection[Any],
    document_ids: list[str],
    log: Callable[[str], None] | None = None,
) -> list[tuple[str, int, int, int, int]]:
    """Per-document effect counts: total, textual, applied, and matched to a local provision."""
    return connection.execute(
        """
        select
            e.affected_document_id,
            count(*)::int as effects,
            count(*) filter (where e.textual_kind = 'T')::int as textual,
            count(*) filter (where e.applied)::int as applied,
            count(*) filter (where exists (
                select 1
                from effect_provisions ep
                join provisions p
                  on p.document_id = e.affected_document_id
                 and p.number = ep.section_number
                where ep.effect_id = e.id and ep.side = 'affected'
            ))::int as provision_matched
        from effects e
        where e.affected_document_id = any(%s)
        group by e.affected_document_id
        order by effects desc
        """,
        (document_ids,),
    ).fetchall()
