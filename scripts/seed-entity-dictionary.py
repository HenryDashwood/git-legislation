"""Seed the orgs entity dictionary (orgs.entities / entity_aliases).

Sources, in order:
  1. GOV.UK organisations register (https://www.gov.uk/api/organisations) -
     canonical: all ~1,262 organisations including closed ones, with closure
     reasons, successor links, hierarchy, and official abbreviations. Fetched
     live; cached at var/entities/govuk-orgs.json.
  2. machineryofgovernment.uk entities (var/entities/mog-entities.json,
     extracted from the site's JS bundle) - adds typed subtypes and the
     officials (ministerial offices) the register doesn't carry.
  3. legislation.gov.uk /id/organisation/ URIs already present in
     duties.duty_actor_matches.
  4. A small manual alias list for statutory designations verified in the
     statute book (e.g. NESO's statutory name under the Energy Act 2023).

Aliases are observed strings only - abbreviations from the register, former
names along changed_name successor chains, machineryofgovernment display
names, and manually verified statutory names. Nothing is generated.
Idempotent: safe to re-run after a register refresh.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import certifi
import httpx
import psycopg

CACHE_DIR = Path("var/entities")
GOVUK_CACHE = CACHE_DIR / "govuk-orgs.json"
MOG_PATH = CACHE_DIR / "mog-entities.json"

# (govuk_slug, alias, alias_kind) - statutory designations checked by hand.
# NESO is designated as the Independent System Operator and Planner under
# s.162 Energy Act 2023 ("the ISOP"); Ofcom's statutory name is the Office of
# Communications (Communications Act 2003 s.1); Historic England's is the
# Historic Buildings and Monuments Commission for England (National Heritage
# Act 1983 s.32).
MANUAL_ALIASES = [
    ("national-energy-system-operator", "Independent System Operator and Planner", "statutory_name"),
    ("national-energy-system-operator", "ISOP", "abbreviation"),
    ("ofcom", "Office of Communications", "statutory_name"),
    ("historic-england", "Historic Buildings and Monuments Commission for England", "statutory_name"),
]


def normalize(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"^(the|his majesty's|her majesty's|hm)\s+", "", name)
    return re.sub(r"[^a-z0-9 ]", "", name).strip()


def fetch_govuk_orgs() -> list[dict]:
    if GOVUK_CACHE.exists():
        print(f"using cached {GOVUK_CACHE}")
        return json.load(open(GOVUK_CACHE))
    results, page = [], 1
    with httpx.Client(headers={"User-Agent": "git-legislation-research"}, timeout=30) as client:
        while True:
            data = client.get(f"https://www.gov.uk/api/organisations?page={page}").json()
            results.extend(data["results"])
            if page >= data["pages"]:
                break
            page += 1
            time.sleep(0.2)
    GOVUK_CACHE.write_text(json.dumps(results))
    print(f"fetched {len(results)} organisations from GOV.UK")
    return results


def slug_of(reference: dict) -> str:
    return reference["id"].rstrip("/").rsplit("/", 1)[-1]


def upsert_entity(cursor, **fields) -> int:
    """Insert or update by whichever external key is present; returns entity id."""
    for key in ("govuk_slug", "mog_id"):
        if fields.get(key):
            cursor.execute(
                f"""
                insert into orgs.entities (name, kind, org_type, status, closed_reason, closed_at,
                                           govuk_slug, mog_id)
                values (%(name)s, %(kind)s, %(org_type)s, %(status)s, %(closed_reason)s, %(closed_at)s,
                        %(govuk_slug)s, %(mog_id)s)
                on conflict ({key}) do update
                    set name = excluded.name, org_type = excluded.org_type,
                        status = excluded.status, closed_reason = excluded.closed_reason,
                        closed_at = excluded.closed_at
                returning id
                """,
                {
                    "name": fields["name"],
                    "kind": fields["kind"],
                    "org_type": fields.get("org_type"),
                    "status": fields.get("status"),
                    "closed_reason": fields.get("closed_reason"),
                    "closed_at": fields.get("closed_at"),
                    "govuk_slug": fields.get("govuk_slug"),
                    "mog_id": fields.get("mog_id"),
                },
            )
            return cursor.fetchone()[0]
    raise ValueError("entity needs govuk_slug or mog_id")


def add_alias(cursor, entity_id: int, alias: str, alias_kind: str, source: str) -> None:
    cursor.execute("select name from orgs.entities where id = %s", (entity_id,))
    if normalize(cursor.fetchone()[0]) == normalize(alias):
        return
    cursor.execute(
        """
        insert into orgs.entity_aliases (entity_id, alias, alias_kind, source)
        values (%s, %s, %s, %s)
        on conflict (entity_id, lower(alias)) do nothing
        """,
        (entity_id, alias, alias_kind, source),
    )


def main() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not os.environ.get("DB_URL"):
        sys.exit("DB_URL is not set - run `source .envrc` first")
    orgs = fetch_govuk_orgs()
    connection = psycopg.connect(
        os.environ["DB_URL"].split("?")[0], sslmode="verify-full", sslrootcert=certifi.where()
    )
    cursor = connection.cursor()

    # 1. GOV.UK register: entities, then hierarchy/succession, then aliases.
    id_by_slug: dict[str, int] = {}
    for org in orgs:
        details = org["details"]
        id_by_slug[details["slug"]] = upsert_entity(
            cursor,
            name=org["title"],
            kind="body",
            org_type=org["format"],
            status=details["govuk_status"],
            closed_reason=details.get("govuk_closed_status"),
            closed_at=(details.get("closed_at") or "")[:10] or None,
            govuk_slug=details["slug"],
            mog_id=None,
        )
    for org in orgs:
        entity_id = id_by_slug[org["details"]["slug"]]
        parent = next((id_by_slug.get(slug_of(p)) for p in org["parent_organisations"]), None)
        successor = next((id_by_slug.get(slug_of(s)) for s in org["superseding_organisations"]), None)
        cursor.execute(
            "update orgs.entities set parent_id = %s, successor_id = %s where id = %s",
            (parent, successor, entity_id),
        )
        abbreviation = org["details"].get("abbreviation")
        if abbreviation and abbreviation.strip():
            add_alias(cursor, entity_id, abbreviation.strip(), "abbreviation", "govuk")
    # A changed_name predecessor's title is a former name of its successor.
    former_names = 0
    for org in orgs:
        if org["details"].get("govuk_closed_status") == "changed_name" and org["superseding_organisations"]:
            successor_id = id_by_slug.get(slug_of(org["superseding_organisations"][0]))
            if successor_id:
                add_alias(cursor, successor_id, org["title"], "former_name", "govuk")
                former_names += 1
    print(f"gov.uk: {len(orgs)} entities, {former_names} former-name aliases")

    # 2. machineryofgovernment: match by normalised name, else insert.
    by_norm: dict[str, int] = {}
    cursor.execute("select id, name from orgs.entities")
    for entity_id, name in cursor.fetchall():
        by_norm.setdefault(normalize(name), entity_id)
    mog_matched = mog_new = 0
    if MOG_PATH.exists():
        for record in json.load(open(MOG_PATH)):
            existing = by_norm.get(normalize(record["name"]))
            if existing:
                cursor.execute(
                    "update orgs.entities set mog_id = %s where id = %s and mog_id is null",
                    (record["id"], existing),
                )
                mog_matched += 1
            else:
                kind = "office" if record["category"] == "official" else "body"
                entity_id = upsert_entity(
                    cursor,
                    name=record["name"],
                    kind=kind,
                    org_type=record.get("subtype"),
                    status="live",
                    closed_reason=None,
                    closed_at=None,
                    govuk_slug=None,
                    mog_id=record["id"],
                )
                by_norm.setdefault(normalize(record["name"]), entity_id)
                mog_new += 1
        print(f"machineryofgovernment: {mog_matched} matched, {mog_new} new entities")
    else:
        print(f"{MOG_PATH} missing; skipping machineryofgovernment enrichment")

    # 3. legislation.gov.uk organisation URIs observed in the duties data.
    cursor.execute(
        """
        select distinct body_uri, body_name from duties.duty_actor_matches
        where body_uri is not null
        """
    )
    uri_matched = 0
    for uri, body_name in cursor.fetchall():
        entity_id = by_norm.get(normalize(body_name))
        if entity_id:
            cursor.execute(
                "update orgs.entities set legislation_uri = %s where id = %s and legislation_uri is null",
                (uri, entity_id),
            )
            uri_matched += 1
    print(f"legislation.gov.uk URIs attached: {uri_matched}")

    # 4. Manual statutory designations.
    for slug, alias, alias_kind in MANUAL_ALIASES:
        if slug in id_by_slug:
            add_alias(cursor, id_by_slug[slug], alias, alias_kind, "manual")

    connection.commit()
    cursor.execute("select kind, count(*) from orgs.entities group by 1")
    print("entities by kind:", dict(cursor.fetchall()))
    cursor.execute("select count(*) from orgs.entity_aliases")
    print("aliases:", cursor.fetchone()[0])
    connection.close()


if __name__ == "__main__":
    main()
