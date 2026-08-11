"""Task-first search over statutory powers: "what powers let me do xyz?".

Two stages, mirroring how the served app should work:

  1. Rewrite. One cheap LLM call turns a minister's question into a query
     plan - the bodies it targets, which instrument facets apply, and the
     statutory vocabulary for the everyday words ("blackout" -> "civil
     emergency", "shortage of electricity", "security of supply"). This is
     what closes the gap between how people ask and how statutes are drafted.

  2. Rank. One SQL query scores powers using the structured columns the
     enrichment produced - the direction-power flag, the instrument facet,
     resolved targets, and act-scoped class membership - on top of the
     full-text rank. Deliberately no embeddings: the rewrite stage already
     handles vocabulary mismatch, and structured ranking alone puts the
     right provisions on top (see the acceptance test in the module docs).

Usage:
    source .envrc
    uv run python scripts/search-powers.py "force NESO to give me information about a blackout"
    uv run python scripts/search-powers.py --no-rewrite "give directions to a licence holder"
"""

import json
import os
import sys

import certifi
import httpx
import psycopg

MODEL = "deepseek/deepseek-v4-flash-0731"
INSTRUMENTS = (
    "legislate direct guide appoint establish fund authorise charge inspect enforce adjudicate acquire other"
).split()

REWRITE_PROMPT = """You turn a UK government minister's question into a search plan over a database of \
statutory powers extracted from UK legislation. The user is a minister asking what powers are \
available to them. Return a JSON object:

{"targets": [<str>, ...], "instruments": [<str>, ...], "terms": [<str>, ...], "domain": [<str>, ...]}

- "targets": bodies, offices, or classes of person the power would be exercised over, as the user \
named them AND as legislation would name them. Include official and statutory names. \
e.g. "NESO" -> ["NESO", "National Energy System Operator", "Independent System Operator and \
Planner", "electricity system operator", "licence holder"]. Empty list if the question names no target.
- "instruments": which of these apply, most relevant first - legislate, direct, guide, appoint, \
establish, fund, authorise, charge, inspect, enforce, adjudicate, acquire. "force X to tell me \
something" is ["direct", "inspect"]. "close down a scheme" is ["establish", "legislate"].
- "terms": the words UK statutes actually use for what the user described. Translate everyday \
language into statutory language: "blackout" -> ["civil emergency", "shortage of electricity", \
"security of supply", "electricity supply emergency"]; "tell me" -> ["furnish information", \
"provide information", "require information"]. 4-10 terms.
- "domain": subject-matter words that would appear in the title of a relevant Act, \
e.g. ["electricity", "energy"]. 0-4 words.

Return only the JSON object."""

SEARCH_SQL = """
with q as (
    select websearch_to_tsquery('english', %(tsquery)s) as tsq
),
target_hits as (
    -- powers whose extracted target matches a named body, or resolves to a
    -- class that body belongs to *within the enacting Act* (scoped membership)
    select distinct t.duty_id
    from duties.power_targets t
    left join orgs.entities e on e.id = t.entity_id
    left join orgs.entity_class_members m on m.class_id = e.id
    left join orgs.entities member on member.id = m.entity_id
    left join duties.duties dd on dd.id = t.duty_id
    where t.target_text ILIKE any(%(target_patterns)s)
       or e.name ILIKE any(%(target_patterns)s)
       or (member.name ILIKE any(%(target_patterns)s) and m.document_id = dd.document_id)
)
select d.enactment_title, d.document_id, d.section_path, d.actor,
       pe.instrument, pe.is_direction_power,
       round((
           ts_rank(d.action_tsv, q.tsq)
         + case when th.duty_id is not null then 0.40 else 0 end
         + case when pe.instrument = any(%(instruments)s) then 0.25 else 0 end
         + case when pe.is_direction_power and 'direct' = any(%(instruments)s) then 0.30 else 0 end
         + case when %(domain)s <> '' and d.enactment_title ~* %(domain)s then 0.25 else 0 end
         + case when %(domain)s <> '' and d.action ~* %(domain)s then 0.20 else 0 end
       )::numeric, 3) as score,
       d.action, d.condition
from duties.duties d
join duties.power_enrichments pe on pe.duty_id = d.id
left join target_hits th on th.duty_id = d.id
, q
where d.modality in ('power', 'both')
  and (%(ministerial_only)s is false or d.actor ~* %(minister_re)s)
  and (d.action_tsv @@ q.tsq or th.duty_id is not null)
order by score desc
limit %(limit)s
"""

MINISTER_RE = (
    "secretary of state|^the ministers?$|^ministers?$|treasury|lord chancellor|scottish ministers|welsh ministers"
)


def rewrite(question: str) -> dict:
    """One LLM call: minister's words -> query plan."""
    response = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": REWRITE_PROMPT},
                {"role": "user", "content": question},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "reasoning": {"enabled": False},
            "max_tokens": 800,
        },
        timeout=120,
    )
    response.raise_for_status()
    plan = json.loads(response.json()["choices"][0]["message"]["content"])
    plan["instruments"] = [i for i in plan.get("instruments", []) if i in INSTRUMENTS]
    return plan


def search(connection, plan: dict, ministerial_only: bool = True, limit: int = 8) -> list:
    terms = list(plan.get("terms") or []) + list(plan.get("targets") or [])
    tsquery = " OR ".join(f'"{t}"' for t in terms if t) or "power"
    domain = "|".join(w for w in (plan.get("domain") or []) if w)
    with connection.cursor() as cursor:
        cursor.execute(
            SEARCH_SQL,
            {
                "tsquery": tsquery,
                "target_patterns": [f"%{t}%" for t in (plan.get("targets") or ["\x00"])],
                "instruments": plan.get("instruments") or [],
                "domain": domain,
                "ministerial_only": ministerial_only,
                "minister_re": MINISTER_RE,
                "limit": limit,
            },
        )
        return cursor.fetchall()


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--no-rewrite"]
    if not args:
        sys.exit('usage: search-powers.py "what do you want to do?"')
    question = " ".join(args)
    for var in ("DB_URL", "OPENROUTER_API_KEY"):
        if not os.environ.get(var):
            sys.exit(f"{var} is not set - run `source .envrc` first")

    if "--no-rewrite" in sys.argv:
        plan = {"targets": [], "instruments": [], "terms": question.split(), "domain": []}
    else:
        plan = rewrite(question)
        print(f"question: {question}")
        print(f"  targets:     {plan.get('targets')}")
        print(f"  instruments: {plan.get('instruments')}")
        print(f"  terms:       {plan.get('terms')}")
        print(f"  domain:      {plan.get('domain')}\n")

    connection = psycopg.connect(
        os.environ["DB_URL"].split("?")[0], sslmode="verify-full", sslrootcert=certifi.where()
    )
    for i, row in enumerate(search(connection, plan), 1):
        title, doc_id, path, actor, instrument, is_direction, score, action, condition = row
        flag = ", direction power" if is_direction else ""
        print(f"{i}. [{score}] {title} — {path}   ({instrument}{flag})")
        print(f"   {actor} may {action[:150]}")
        if condition:
            print(f"   only if: {condition[:110]}")
        print(f"   https://www.legislation.gov.uk/{doc_id}/{path}\n")
    connection.close()


if __name__ == "__main__":
    main()
