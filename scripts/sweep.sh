#!/bin/zsh
# Full liteparse sweep over PDF-backed metadata-only documents.
# Text-layer-rich 20th-century series first; image-only historical types last
# (they yield little without OCR and are queued for GPU marker later).
#
# Politeness: 0.5s between PDF downloads, and a 30-minute pause whenever a
# batch is mostly failures (legislation.gov.uk signals sustained-rate blocks
# with HTTP 432; the fetch client also backs off per-request on 429/432).
set -u
export DB_URL="postgres://postgres:postgres@localhost:5433/british_legislation?sslmode=disable"
cd /Users/henrydashwood/git-legislation

BATCH=500
MAX_ITERS_PER_TYPE=250
DELAY_SECONDS=0.5
RATE_LIMIT_PAUSE_SECONDS=1800
FAILURE_CIRCUIT_THRESHOLD=100
TYPES=(uksi nisro nisr ssi wsi ukla ukpga ukppa ukcm nisi ukmo ALL)

log() { print -r -- "[$(date '+%F %T')] $*"; }

for t in "${TYPES[@]}"; do
  type_args=()
  if [[ "$t" != "ALL" ]]; then
    type_args=(--legislation-type "$t")
  fi
  iters=0
  while (( iters < MAX_ITERS_PER_TYPE )); do
    (( iters++ ))
    out=$(uv run git-legislation parse-pdf-sample --no-ocr --limit $BATCH --delay-seconds $DELAY_SECONDS "${type_args[@]}" 2>&1)
    summary=$(print -r -- "$out" | grep -E 'Scanned [0-9]+ candidate|Extracted [0-9]+ words' | tr '\n' ' ')
    batch_failures=$(print -r -- "$out" | grep -oE 'Scanned [0-9]+ candidate PDFs; [0-9]+ failures' | grep -oE '[0-9]+ failures' | grep -oE '[0-9]+')
    log "$t parse[$iters]: $summary"
    uv run git-legislation normalize-liteparse-markdown-sample --limit $BATCH "${type_args[@]}" > /dev/null 2>&1
    if [[ -n "${batch_failures:-}" && "$batch_failures" -ge "$FAILURE_CIRCUIT_THRESHOLD" ]]; then
      # Verify before pausing: a healthy probe means the failures are
      # broken documents (handled by 3-strike exclusion), not a rate limit.
      probe=$(curl -s -m 15 -A 'git-legislation/0.1' -o /dev/null -w '%{http_code}' 'https://www.legislation.gov.uk/ukla/1932/37/pdfs/ukla_19320037_en.pdf')
      if [[ "$probe" == "200" ]]; then
        log "$t: $batch_failures failures but upstream healthy (probe 200) - continuing"
      else
        log "$t: $batch_failures failures and probe returned $probe - rate limited; pausing ${RATE_LIMIT_PAUSE_SECONDS}s"
        sleep $RATE_LIMIT_PAUSE_SECONDS
        continue
      fi
    fi
    scanned=$(print -r -- "$out" | grep -o 'Scanned [0-9]* candidate' | head -1 | grep -o '[0-9]*' | head -1)
    if [[ -z "${scanned:-}" || "$scanned" -lt "$BATCH" ]]; then
      log "$t: exhausted after $iters batches"
      break
    fi
  done
done

# Drain any remaining un-normalized reports.
while true; do
  norm=$(uv run git-legislation normalize-liteparse-markdown-sample --limit $BATCH 2>&1 | grep -c '^- ' || true)
  log "normalize drain: $norm"
  [[ "$norm" -lt "$BATCH" ]] && break
done

log "SWEEP COMPLETE"
