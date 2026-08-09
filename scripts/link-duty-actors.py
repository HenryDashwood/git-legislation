"""Link the duties actor vocabulary to the orgs entity dictionary.

Takes every distinct body name in duties.duty_actor_matches (~824) and asks
DeepSeek V4 Flash to make one conservative call per name:

  match <id>  - the name refers to one of the candidate entities we supply
                (candidates come from fuzzy-matching the dictionary; the model
                cannot name an entity outside the list)
  class       - a generic legal category, not an organisation ("local
                authority", "constable", "harbour authority")
  office      - an officeholder addressed as such ("Secretary of State",
                "sheriff") rather than an organisation
  none        - unresolvable / too ambiguous; leave it alone

Matches where the string differs from the entity name become actor_name
aliases (source llm-link). class/office names become new kind=class/office
entities so class-addressed powers have something to resolve to. Names the
model calls none stay unlinked - nothing is invented. Idempotent.
"""

import asyncio
import difflib
import json
import os
import sys

import certifi
import httpx
import psycopg

MODEL = "deepseek/deepseek-v4-flash-0731"
BATCH_SIZE = 25
MAX_IN_FLIGHT = 8

SYSTEM_PROMPT = """You resolve actor names found in UK legislation against a dictionary of \
government entities. For each input item you get the name, how often it appears, and a list of \
candidate entities (id, name, type). Return a JSON object:
  {"rows": [{"name": <str>, "decision": "match"|"class"|"office"|"none", "entity_id": <int or null>}]}

Rules, in order:
- "match" + entity_id ONLY when the name clearly refers to that candidate - the same \
organisation under its own, an abbreviated, or a former name. Legal certainty matters more than \
coverage: when torn between match and none, answer none.
- "class" when the name is a generic legal category with many members: "local authority", \
"district council", "harbour authority", "enforcement authority", "the court", "an applicant".
- "office" when the name is an officeholder addressed as an office: "Secretary of State", \
"Lord Chancellor", "sheriff", "constable", "coroner", "Attorney General".
- "none" when it is ambiguous, historical with no candidate, or not identifiable.
- entity_id must come from the candidate list or be null. Never guess an id.
Exactly one row per input item. Return only the JSON object."""


def normalize(name: str) -> str:
    import re

    name = name.lower().strip()
    name = re.sub(r"^(the|his majesty's|her majesty's|hm)\s+", "", name)
    return re.sub(r"[^a-z0-9 ]", "", name).strip()


def candidates_for(name: str, catalog: dict[str, list]) -> list[dict]:
    """Fuzzy shortlist from entity names and aliases."""
    norm = normalize(name)
    scored: dict[int, tuple[float, str, str]] = {}
    close = set(difflib.get_close_matches(norm, catalog.keys(), n=8, cutoff=0.72))
    for key in catalog:
        if key in close or (len(norm) > 8 and (norm in key or key in norm)):
            for entity_id, display, org_type in catalog[key]:
                ratio = difflib.SequenceMatcher(None, norm, key).ratio()
                if entity_id not in scored or ratio > scored[entity_id][0]:
                    scored[entity_id] = (ratio, display, org_type)
    ranked = sorted(scored.items(), key=lambda item: -item[1][0])[:6]
    return [{"id": eid, "name": display, "type": org_type or ""} for eid, (_, display, org_type) in ranked]


async def classify_batch(client, semaphore, batch):
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(batch, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "reasoning": {"enabled": False},
        "max_tokens": 4000,
    }
    async with semaphore:
        for attempt in range(4):
            try:
                response = await client.post("/chat/completions", json=body)
                if response.status_code in (429, 500, 502, 503):
                    await asyncio.sleep(2**attempt * 2)
                    continue
                response.raise_for_status()
                content = response.json()["choices"][0].get("message", {}).get("content")
                if not content:
                    continue
                parsed = json.loads(content)
                return parsed["rows"] if isinstance(parsed, dict) and "rows" in parsed else parsed
            except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError) as error:
                print(f"batch retry {attempt}: {error}", file=sys.stderr)
                await asyncio.sleep(2**attempt * 2)
    return []


async def main() -> None:
    for var in ("DB_URL", "OPENROUTER_API_KEY"):
        if not os.environ.get(var):
            sys.exit(f"{var} is not set - run `source .envrc` first")
    connection = psycopg.connect(
        os.environ["DB_URL"].split("?")[0], sslmode="verify-full", sslrootcert=certifi.where()
    )
    cursor = connection.cursor()

    catalog: dict[str, list] = {}
    cursor.execute("select id, name, org_type from orgs.entities where kind in ('body','office')")
    for entity_id, name, org_type in cursor.fetchall():
        catalog.setdefault(normalize(name), []).append((entity_id, name, org_type))
    cursor.execute(
        """select a.entity_id, a.alias, e.org_type from orgs.entity_aliases a
           join orgs.entities e on e.id = a.entity_id"""
    )
    for entity_id, alias, org_type in cursor.fetchall():
        catalog.setdefault(normalize(alias), []).append((entity_id, alias, org_type))

    cursor.execute(
        """select m.body_name, count(*) from duties.duty_actor_matches m
           where not exists (
               select 1 from orgs.entity_aliases a where lower(a.alias) = lower(m.body_name)
           ) and not exists (
               select 1 from orgs.entities e where lower(e.name) = lower(m.body_name)
           )
           group by 1 order by 2 desc"""
    )
    names = cursor.fetchall()
    print(f"{len(names)} unresolved actor names to classify")

    items = [
        {"name": name, "occurrences": count, "candidates": candidates_for(name, catalog)} for name, count in names
    ]
    batches = [items[i : i + BATCH_SIZE] for i in range(0, len(items), BATCH_SIZE)]
    semaphore = asyncio.Semaphore(MAX_IN_FLIGHT)
    async with httpx.AsyncClient(
        base_url="https://openrouter.ai/api/v1",
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
        timeout=240,
    ) as client:
        results = await asyncio.gather(*[classify_batch(client, semaphore, b) for b in batches])

    valid_ids = {eid for lists in catalog.values() for eid, _, _ in lists}
    counts = {"match": 0, "class": 0, "office": 0, "none": 0, "invalid": 0}
    for rows in results:
        for row in rows:
            name, decision = row.get("name", ""), row.get("decision")
            if not name:
                continue
            if decision == "match" and row.get("entity_id") in valid_ids:
                cursor.execute(
                    """insert into orgs.entity_aliases (entity_id, alias, alias_kind, source)
                       select %s, %s, 'actor_name', 'llm-link'
                       where not exists (select 1 from orgs.entities where id=%s and lower(name)=lower(%s))
                       on conflict (entity_id, lower(alias)) do nothing""",
                    (row["entity_id"], name, row["entity_id"], name),
                )
                counts["match"] += 1
            elif decision in ("class", "office"):
                cursor.execute(
                    """insert into orgs.entities (name, kind, status)
                       select %s, %s, 'n/a'
                       where not exists (
                           select 1 from orgs.entities where kind=%s and lower(name)=lower(%s))""",
                    (name, decision, decision, name),
                )
                counts[decision] += 1
            elif decision == "none":
                counts["none"] += 1
            else:
                counts["invalid"] += 1
    connection.commit()
    print("decisions:", counts)

    cursor.execute(
        """select count(*), count(*) filter (where
               exists (select 1 from orgs.entities e where lower(e.name)=lower(m.body_name))
               or exists (select 1 from orgs.entity_aliases a where lower(a.alias)=lower(m.body_name)))
           from duties.duty_actor_matches m"""
    )
    total, resolved = cursor.fetchone()
    print(f"duty_actor_matches rows resolving to the dictionary: {resolved}/{total} ({100 * resolved / total:.0f}%)")
    connection.close()


if __name__ == "__main__":
    asyncio.run(main())
