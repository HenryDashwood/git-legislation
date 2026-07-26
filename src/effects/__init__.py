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
    # "coming into force" is the commonest of these and changes no words: it
    # records a provision starting to have legal effect, so counting it as a
    # textual amendment makes staged commencement look like a pipeline failure.
    if "commencement" in normalized or "force" in normalized:
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


CONFIRMATION_SQL = """
with eff as (
    select e.id, e.affected_document_id doc, e.in_force_date d,
           ep.section_number num, ep.provision_kind kind
    from effects e
    join effect_provisions ep on ep.effect_id = e.id and ep.side = 'affected'
    where e.affected_document_id = %s
      and e.in_force_date is not null
      and e.applied
      and e.textual_kind = 'T'
      and ep.section_number is not null
),
paired as (
    select eff.*,
      (select id from document_versions v
        where v.document_id = eff.doc and v.snapshot_date < eff.d
        order by v.snapshot_date desc limit 1) before_id,
      (select id from document_versions v
        where v.document_id = eff.doc and v.snapshot_date >= eff.d
        order by v.snapshot_date asc limit 1) after_id
    from eff
)
select
  count(*)::int total,
  count(*) filter (where before_id is null or after_id is null)::int outside_range,
  count(*) filter (where before_id is not null and after_id is not null
                     and (pb.markdown is null or pa.markdown is null))::int provision_absent,
  count(*) filter (where pb.markdown is not null and pa.markdown is not null
                     and pb.markdown <> pa.markdown)::int text_differs,
  count(*) filter (where pb.markdown is not null and pa.markdown is not null
                     and pb.markdown = pa.markdown)::int text_identical
from paired
left join provisions pb
  on pb.version_id = paired.before_id and pb.number = paired.num and pb.provision_type = paired.kind
left join provisions pa
  on pa.version_id = paired.after_id and pa.number = paired.num and pa.provision_type = paired.kind
"""


@dataclass(frozen=True)
class EffectConfirmation:
    document_id: str
    total: int
    outside_range: int
    provision_absent: int
    text_differs: int
    text_identical: int

    @property
    def checkable(self) -> int:
        return self.text_differs + self.text_identical

    @property
    def confirmed_rate(self) -> float | None:
        return self.text_differs / self.checkable if self.checkable else None


def confirm_effects_against_diffs(
    connection: psycopg.Connection[Any],
    document_id: str,
) -> EffectConfirmation:
    """Check whether applied textual effects coincide with a real change in our text.

    For each effect, compare the provision it names in the last version before
    its in-force date against the first version on or after it. A high rate of
    identical text means our text or the provision join is wrong, not that the
    upstream record is: this is an independent audit of the diff pipeline
    against the official amendment record.
    """
    row = connection.execute(CONFIRMATION_SQL, (document_id,)).fetchone()
    total, outside_range, provision_absent, text_differs, text_identical = row or (0, 0, 0, 0, 0)
    return EffectConfirmation(
        document_id=document_id,
        total=total,
        outside_range=outside_range,
        provision_absent=provision_absent,
        text_differs=text_differs,
        text_identical=text_identical,
    )


def render_effect_confirmations(confirmations: list[EffectConfirmation]) -> str:
    lines = [f"{'document':18} {'checked':>8} {'confirmed':>10} {'identical':>10} {'absent':>7} {'rate':>6}"]
    differs = identical = absent = 0
    for confirmation in confirmations:
        rate = confirmation.confirmed_rate
        lines.append(
            f"{confirmation.document_id:18} {confirmation.checkable:>8} {confirmation.text_differs:>10} "
            f"{confirmation.text_identical:>10} {confirmation.provision_absent:>7} "
            f"{f'{rate * 100:.0f}%' if rate is not None else 'n/a':>6}"
        )
        differs += confirmation.text_differs
        identical += confirmation.text_identical
        absent += confirmation.provision_absent
    checkable = differs + identical
    overall = f"{differs / checkable * 100:.0f}%" if checkable else "n/a"
    lines.append(f"{'TOTAL':18} {checkable:>8} {differs:>10} {identical:>10} {absent:>7} {overall:>6}")
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
                 -- Kind must agree: matching on number alone let an effect on
                 -- "Sch. 5" resolve to section 5.
                 and p.provision_type = ep.provision_kind
                where ep.effect_id = e.id and ep.side = 'affected'
            ))::int as provision_matched
        from effects e
        where e.affected_document_id = any(%s)
        group by e.affected_document_id
        order by effects desc
        """,
        (document_ids,),
    ).fetchall()
