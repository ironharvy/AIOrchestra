#!/usr/bin/env bash
# Block until a GitHub issue matching a label appears, then print it as JSON.
#
# Usage:
#   wait-for-issue.sh <repo> <label> [poll_seconds] [max_wait_seconds]
#
# Exits:
#   0  — match found; issue JSON on stdout
#   75 — max_wait reached without a match (EX_TEMPFAIL); re-run to keep waiting
#   1  — gh/jq failure or bad arguments
#
# Why max_wait defaults to 540s: Claude Code's Bash tool caps a single call at
# 600s, so the script self-terminates under that ceiling. A parent loop (shell,
# Claude, cron) can re-invoke on exit 75 to wait indefinitely.

set -euo pipefail

REPO="${1:?repo required (owner/name)}"
LABEL="${2:?label required}"
POLL="${3:-30}"
MAX_WAIT="${4:-540}"

command -v gh >/dev/null || { echo "gh not found on PATH" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq not found on PATH" >&2; exit 1; }

deadline=$(( $(date +%s) + MAX_WAIT ))

while :; do
  out=$(gh issue list \
    --repo "$REPO" \
    --label "$LABEL" \
    --state open \
    --json number,title,body,labels,assignees,comments \
    --limit 1)

  if [[ "$(jq 'length' <<<"$out")" -gt 0 ]]; then
    jq '.[0]' <<<"$out"
    exit 0
  fi

  now=$(date +%s)
  if (( now >= deadline )); then
    echo "no matching issue for repo=$REPO label=$LABEL after ${MAX_WAIT}s" >&2
    exit 75
  fi

  remaining=$(( deadline - now ))
  sleep "$(( POLL < remaining ? POLL : remaining ))"
done
