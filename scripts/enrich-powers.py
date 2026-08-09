"""Enrich every power in duties.duties with targets, instrument class, and a
direction-power flag, using DeepSeek V4 Flash via OpenRouter.

Two phases, both resumable:
  1. dump: streams (id, actor, action, condition) for modality in (power, both)
     to var/enrichment/powers-input.jsonl (skipped if the file exists).
  2. enrich: batches rows to the model, appending to var/enrichment/
     powers-enriched.jsonl. Already-enriched ids are skipped on restart, so
     Ctrl-C / crashes / re-runs are safe.

Run overnight from the repo root (caffeinate stops the Mac sleeping mid-run):

    source .envrc
    caffeinate -i uv run python scripts/enrich-powers.py

Pinned to the 0731 snapshot rather than the -latest alias: same model today,
30% cheaper output ($0.18/M vs $0.252/M). Reasoning must stay disabled - with
it on, ~90% of output tokens are reasoning and cost is ~10x (see the
2026-08-09 pilot). Expected total: ~75M in / ~24M out, ~$11, ~6h at 32-way
concurrency.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import certifi
import httpx
import psycopg

OUT_DIR = Path("var/enrichment")
INPUT_PATH = OUT_DIR / "powers-input.jsonl"
OUTPUT_PATH = OUT_DIR / "powers-enriched.jsonl"
MODEL = "deepseek/deepseek-v4-flash-0731"
BATCH_SIZE = 20
MAX_IN_FLIGHT = int(os.environ.get("ENRICH_CONCURRENCY", "32"))

SYSTEM_PROMPT = """You extract structured facts from statutory powers found in UK legislation.

For each input row (id, actor, action, condition) return:
  {"id": <int>, "targets": [<str>, ...], "is_direction_power": <bool>, "instrument": <str>}

"targets": the person, body, or class of persons over whom or in respect of whom the power is \
exercised. The actor HOLDS the power; you are naming who it is exercised OVER. Copy the wording \
used in the text, singular, without leading articles ("Environment Agency", "planning authority", \
"applicant"). Return [] when the power has no target at all - powers to make regulations, issue \
guidance at large, publish reports, determine fees, or include provision in an order have no \
target. Do not invent bodies the text does not mention. Never return a bare pronoun or a \
country name as a target.

"is_direction_power": true ONLY when the actor can issue a binding instruction to ANOTHER body \
or officeholder about how that body exercises its own statutory functions. This is the narrow \
concept of one public authority steering another.
  true:  "give directions to the planning authority requiring them to furnish information"
  true:  "direct the Agency as to the exercise of its functions under section 5"
  false: "require a person in breach to provide information"        (enforcement against a person)
  false: "direct that an applicant shall comply with procedural requirements"  (procedural ruling)
  false: "give directions prohibiting mooring of vessels"           (regulating the public)
  false: "vary or discharge a direction previously made"            (altering, not issuing)
  false: "apply to the Tribunal for a direction"                    (requesting, not issuing)
If the recipient is a private person, a regulated entity, or the public at large, it is false.

"instrument": exactly one of these categories, the legal instrument the power uses:
  "legislate"     make/amend/revoke regulations, orders, rules, schemes, or other secondary legislation
  "direct"        give directions or binding instructions to a body or person
  "guide"         issue guidance, codes of practice, or advice
  "appoint"       appoint, designate, nominate, or remove a person or body from a role
  "establish"     create, constitute, abolish, or restructure a body, office, or scheme
  "fund"          make grants or loans, pay compensation or fees, provide financial assistance
  "authorise"     grant/refuse/vary/revoke licences, consents, permits, approvals, exemptions
  "charge"        set, determine, or recover fees, charges, levies, or penalties
  "inspect"       enter premises, inspect, investigate, require information or documents
  "enforce"       serve notices, prosecute, impose sanctions, seize, prohibit, or compel compliance
  "adjudicate"    determine applications/appeals/disputes, make findings, give rulings
  "acquire"       acquire, dispose of, or manage land or other property
  "other"         none of the above fits

Return a JSON object {"rows": [...]} with exactly one entry per input row. No other text."""


def dump_powers() -> None:
    if INPUT_PATH.exists():
        print(f"{INPUT_PATH} exists; skipping dump")
        return
    url = os.environ["DB_URL"].split("?")[0]
    count = 0
    with (
        psycopg.connect(url, sslmode="verify-full", sslrootcert=certifi.where()) as conn,
        conn.cursor(name="powers_dump") as cursor,
        open(INPUT_PATH, "w") as out,
    ):
        cursor.itersize = 10_000
        cursor.execute(
            "select id, actor, action, condition from duties.duties where modality in ('power', 'both') order by id"
        )
        for row_id, actor, action, condition in cursor:
            out.write(
                json.dumps(
                    {"id": row_id, "actor": actor, "action": action, "condition": condition or ""},
                    ensure_ascii=False,
                )
                + "\n"
            )
            count += 1
    print(f"dumped {count} powers to {INPUT_PATH}")


def load_done_ids() -> set[int]:
    if not OUTPUT_PATH.exists():
        return set()
    done = set()
    with open(OUTPUT_PATH) as fh:
        for line in fh:
            try:
                done.add(json.loads(line)["id"])
            except (json.JSONDecodeError, KeyError):
                continue
    return done


async def enrich_batch(client, semaphore, batch, sink):
    payload = [{"id": r["id"], "actor": r["actor"], "action": r["action"], "condition": r["condition"]} for r in batch]
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "reasoning": {"enabled": False},
        "max_tokens": 4000,
    }
    expected = {r["id"] for r in batch}
    async with semaphore:
        for attempt in range(5):
            try:
                response = await client.post("/chat/completions", json=body)
                if response.status_code in (429, 500, 502, 503):
                    await asyncio.sleep(2**attempt * 2)
                    continue
                response.raise_for_status()
                data = response.json()
                usage = data.get("usage", {})
                content = data["choices"][0].get("message", {}).get("content")
                if not content:
                    await asyncio.sleep(2**attempt)
                    continue
                parsed = json.loads(content)
                rows = parsed["rows"] if isinstance(parsed, dict) and "rows" in parsed else parsed
                got = [r for r in rows if isinstance(r, dict) and r.get("id") in expected]
                if len(got) < len(expected) and attempt < 4:
                    continue
                sink.write(got, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
                return
            except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError) as error:
                print(f"batch retry {attempt}: {type(error).__name__}: {error}", file=sys.stderr)
                await asyncio.sleep(2**attempt * 2)
        sink.record_failure(expected)


class Sink:
    """Serializes appends to the output file and tracks progress."""

    def __init__(self, total: int, already_done: int):
        self.handle = open(OUTPUT_PATH, "a")
        self.done = already_done
        self.total = total
        self.failed: list[int] = []
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.started = time.time()

    def write(self, rows, prompt_tokens, completion_tokens):
        for row in rows:
            self.handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.handle.flush()
        self.done += len(rows)
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        if self.done % 5000 < len(rows):
            elapsed = time.time() - self.started
            rate = (self.done * 3600 / elapsed) if elapsed else 0
            print(
                f"{self.done}/{self.total} ({100 * self.done / self.total:.1f}%) "
                f"~{rate:.0f} rows/h, tokens {self.prompt_tokens} in / {self.completion_tokens} out",
                flush=True,
            )

    def record_failure(self, ids):
        self.failed.extend(sorted(ids))


async def enrich() -> None:
    rows = [json.loads(line) for line in open(INPUT_PATH)]
    done = load_done_ids()
    todo = [r for r in rows if r["id"] not in done]
    print(f"{len(rows)} powers total, {len(done)} already enriched, {len(todo)} to do")
    if not todo:
        return
    sink = Sink(total=len(rows), already_done=len(done))
    semaphore = asyncio.Semaphore(MAX_IN_FLIGHT)
    async with httpx.AsyncClient(
        base_url="https://openrouter.ai/api/v1",
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
        timeout=240,
        limits=httpx.Limits(max_connections=MAX_IN_FLIGHT + 4),
    ) as client:
        batches = [todo[i : i + BATCH_SIZE] for i in range(0, len(todo), BATCH_SIZE)]
        await asyncio.gather(*[enrich_batch(client, semaphore, batch, sink) for batch in batches])
    cost = sink.prompt_tokens * 0.09e-6 + sink.completion_tokens * 0.18e-6
    print(f"finished: {sink.done}/{sink.total} enriched, {len(sink.failed)} failed ids")
    print(f"tokens: {sink.prompt_tokens} in / {sink.completion_tokens} out, approx cost ${cost:.2f}")
    if sink.failed:
        failures_path = OUT_DIR / "powers-failed-ids.json"
        json.dump(sink.failed, open(failures_path, "w"))
        print(f"failed ids written to {failures_path}; re-run this script to retry them")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for var in ("DB_URL", "OPENROUTER_API_KEY"):
        if not os.environ.get(var):
            sys.exit(f"{var} is not set - run `source .envrc` first")
    dump_powers()
    asyncio.run(enrich())


if __name__ == "__main__":
    main()
