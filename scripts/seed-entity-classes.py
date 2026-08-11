"""Populate the statutory-class layer of the entity dictionary.

Three steps:
  1. Promote frequently-targeted statutory class strings (observed in
     duties.power_targets) to kind='class' entities. Only strings denoting a
     class of *body* - generic legal persons ("person", "applicant",
     "tenant") are deliberately excluded: they are the objects of regulatory
     powers over private parties, not organisations, and resolving them would
     be meaningless.
  2. Resolve power_targets naming those classes to the class entity. Purely
     mechanical (exact, case-insensitive) - no model involved.
  3. Record hand-verified memberships in orgs.entity_class_members, so a
     power addressed to a class ("the holder of an electricity system
     operator licence") reaches the concrete body (NESO). Membership is
     real-world knowledge with a statutory basis, so it is curated rather
     than generated - the 2026-08-09 linking pass showed the model is ~60%
     precise on entity identity.

Idempotent. Usage:
    source .envrc
    uv run python scripts/seed-entity-classes.py
"""

import os
import sys

import certifi
import psycopg

# Statutory classes of body, taken verbatim from the target vocabulary.
CLASS_TERMS = [
    "licence holder",
    "licensee",
    "system operator",
    "transmission system operator",
    "distribution system operator",
    "relevant system operator",
    "statutory undertaker",
    "utility undertaker",
    "nominated undertaker",
    "competent authority",
    "enforcement authority",
    "relevant authority",
    "appropriate authority",
    "licensing authority",
    "relevant planning authority",
    "street authority",
    "governing body",
    "regulator",
]

# (member entity name, class name, defining enactment document_id, statutory basis).
#
# Membership is ALWAYS scoped to the enactment that defines the class. An
# unscoped claim is wrong, not merely vague: "licence holder" names a
# different set in every Act, and asserting it globally for NESO reached
# Animals (Scientific Procedures) Act and Chemical Weapons Act licensees
# (~1,489 false powers, tested 2026-08-11). Scoped to the Electricity Act
# 1989 the same claim is true and useful - every licence-holder power in that
# Act does apply to NESO.
#
# Each entry is verified by hand against the statute book; the basis is
# stored so a reviewer can check it. The model is not used here: the
# 2026-08-09 linking pass was only ~60% precise on entity identity.
MEMBERSHIPS = [
    (
        "National Energy System Operator",
        "licence holder",
        "ukpga/1989/29",
        "Electricity Act 1989 s.6(1)(da): holds the electricity system operator licence",
    ),
    (
        "National Energy System Operator",
        "system operator",
        "ukpga/1989/29",
        "Electricity Act 1989 s.6(1)(da): the electricity system operator",
    ),
    (
        "National Energy System Operator",
        "licence holder",
        "ukpga/2023/52",
        "Energy Act 2023 s.162: designated Independent System Operator and Planner",
    ),
]


def main() -> None:
    if not os.environ.get("DB_URL"):
        sys.exit("DB_URL is not set - run `source .envrc` first")
    connection = psycopg.connect(
        os.environ["DB_URL"].split("?")[0], sslmode="verify-full", sslrootcert=certifi.where()
    )
    cursor = connection.cursor()

    created = 0
    for term in CLASS_TERMS:
        cursor.execute(
            """insert into orgs.entities (name, kind, status)
               select %s, 'class', 'n/a'
               where not exists (select 1 from orgs.entities where lower(name)=lower(%s))
               returning id""",
            (term, term),
        )
        if cursor.fetchone():
            created += 1
    connection.commit()
    print(f"class entities created: {created} (of {len(CLASS_TERMS)} terms)")

    cursor.execute(
        """update duties.power_targets t
           set entity_id = e.id, resolution = 'exact'
           from orgs.entities e
           where t.resolution = 'unresolved' and e.kind = 'class'
             and lower(e.name) = lower(t.target_text)"""
    )
    print(f"targets resolved to a class: {cursor.rowcount}")
    connection.commit()

    linked = 0
    for member_name, class_name, document_id, basis in MEMBERSHIPS:
        cursor.execute(
            """insert into orgs.entity_class_members (entity_id, class_id, document_id, source)
               select m.id, c.id, %s, %s
               from orgs.entities m, orgs.entities c
               where lower(m.name) = lower(%s) and c.kind = 'class' and lower(c.name) = lower(%s)
               on conflict (entity_id, class_id, document_id) do nothing""",
            (document_id, basis, member_name, class_name),
        )
        linked += cursor.rowcount
    connection.commit()
    print(f"scoped class memberships recorded: {linked}")

    cursor.execute("select kind, count(*) from orgs.entities group by 1 order by 1")
    print("entities by kind:", dict(cursor.fetchall()))
    cursor.execute("select resolution, count(*) from duties.power_targets group by 1 order by 2 desc")
    print("target resolution:", dict(cursor.fetchall()))
    connection.close()


if __name__ == "__main__":
    main()
