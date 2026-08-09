"""Load enrichment output (var/enrichment/powers-enriched.jsonl) into Postgres.

Lands each row in duties.power_enrichments + duties.power_targets, then
resolves every target string against the orgs entity dictionary: exact name
match first, recorded alias second, otherwise left unresolved for a later
reviewed pass (never guessed - see the llm-link precision warning).

Idempotent: re-running upserts enrichments and skips existing targets, so it
can run over a partial overnight file and again over the finished one.

Usage:
    source .envrc
    uv run python scripts/load-enrichment.py [path-to-jsonl]
"""

import json
import os
import sys
from pathlib import Path

import certifi
import psycopg

VALID_INSTRUMENTS = {
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
}
MODEL = "deepseek/deepseek-v4-flash-0731"


def main() -> None:
    if not os.environ.get("DB_URL"):
        sys.exit("DB_URL is not set - run `source .envrc` first")
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("var/enrichment/powers-enriched.jsonl")
    if not path.exists():
        sys.exit(f"{path} not found")

    rows = []
    for line in open(path):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row.get("id"), int):
            rows.append(row)
    print(f"{len(rows)} enrichment rows in {path}")

    connection = psycopg.connect(
        os.environ["DB_URL"].split("?")[0], sslmode="verify-full", sslrootcert=certifi.where()
    )
    cursor = connection.cursor()

    cursor.execute("create temp table staging (duty_id bigint, instrument text, is_direction boolean, target text)")
    with cursor.copy("copy staging (duty_id, instrument, is_direction, target) from stdin") as copy:
        for row in rows:
            instrument = row.get("instrument") if row.get("instrument") in VALID_INSTRUMENTS else "other"
            direction = bool(row.get("is_direction_power"))
            targets = [t.strip() for t in (row.get("targets") or []) if isinstance(t, str) and t.strip()] or [None]
            for target in targets:
                copy.write_row((row["id"], instrument, direction, target))

    cursor.execute(
        """
        insert into duties.power_enrichments (duty_id, instrument, is_direction_power, model)
        select distinct on (s.duty_id) s.duty_id, s.instrument, s.is_direction, %s
        from staging s join duties.duties d on d.id = s.duty_id
        on conflict (duty_id) do update
            set instrument = excluded.instrument,
                is_direction_power = excluded.is_direction_power,
                model = excluded.model, enriched_at = now()
        """,
        (MODEL,),
    )
    print(f"enrichments upserted: {cursor.rowcount}")

    cursor.execute(
        """
        insert into duties.power_targets (duty_id, target_text)
        select distinct s.duty_id, s.target
        from staging s join duties.duties d on d.id = s.duty_id
        where s.target is not null
        on conflict (duty_id, lower(target_text)) do nothing
        """
    )
    print(f"targets inserted: {cursor.rowcount}")

    cursor.execute(
        """
        update duties.power_targets t
        set entity_id = e.id, resolution = 'exact'
        from orgs.entities e
        where t.resolution = 'unresolved' and lower(e.name) = lower(t.target_text)
        """
    )
    exact = cursor.rowcount
    cursor.execute(
        """
        update duties.power_targets t
        set entity_id = a.entity_id, resolution = 'alias'
        from orgs.entity_aliases a
        where t.resolution = 'unresolved' and lower(a.alias) = lower(t.target_text)
        """
    )
    alias = cursor.rowcount
    connection.commit()

    cursor.execute("select resolution, count(*) from duties.power_targets group by 1 order by 2 desc")
    print(f"target resolution: +{exact} exact, +{alias} alias this run; totals {dict(cursor.fetchall())}")
    cursor.execute("select instrument, count(*) from duties.power_enrichments group by 1 order by 2 desc")
    print("instruments:", dict(cursor.fetchall()))
    connection.close()


if __name__ == "__main__":
    main()
