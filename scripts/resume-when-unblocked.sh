#!/bin/zsh
# Wait for legislation.gov.uk's PDF rate-limit block (HTTP 432) to lift, then
# resume the liteparse sweep with polite pacing.
set -u
cd /Users/henrydashwood/git-legislation

PROBE_URL="https://www.legislation.gov.uk/uksi/1960/1/made/data.pdf"

log() { print -r -- "[$(date '+%F %T')] $*"; }

log "waiting for PDF endpoint to unblock (probing every 10 min)"
while true; do
  probe_status=$(curl -s -o /dev/null -w '%{http_code}' "$PROBE_URL")
  if [[ "$probe_status" != "432" ]]; then
    log "PDF endpoint unblocked (status $probe_status) - resuming sweep"
    break
  fi
  sleep 600
done

# Extra cool-down so we do not resume the instant the limiter relents.
sleep 300
nohup zsh var/liteparse-sweep/sweep.sh >> var/liteparse-sweep/sweep.log 2>&1 &
log "sweep relaunched with pid $!"
