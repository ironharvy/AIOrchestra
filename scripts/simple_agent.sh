#!/usr/bin/env bash
# Step 1 of the walking skeleton: poll one GitHub repo for issues carrying a
# trigger label and print them. No dispatch yet — this step exists to confirm
# the "watch for work" half of the loop works end-to-end before we add an agent.
#
# Usage:
#   REPO=owner/name LABEL=agent:run INTERVAL=30 ./scripts/simple_agent.sh
#
# Requirements: gh CLI, authenticated (`gh auth status`).

set -euo pipefail

REPO="${REPO:?set REPO=owner/name}"
LABEL="${LABEL:-agent:run}"
INTERVAL="${INTERVAL:-30}"

command -v gh >/dev/null || { echo "gh CLI not found" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "gh not authenticated — run 'gh auth login'" >&2; exit 1; }

echo "Watching $REPO for open issues labeled '$LABEL' (every ${INTERVAL}s). Ctrl+C to stop."

declare -A seen=()

while true; do
    # --json keeps the output stable; jq gives us one line per issue.
    issues=$(gh issue list \
        --repo "$REPO" \
        --label "$LABEL" \
        --state open \
        --json number,title,url \
        --jq '.[] | "\(.number)\t\(.title)\t\(.url)"' \
        || true)

    if [[ -n "$issues" ]]; then
        while IFS=$'\t' read -r number title url; do
            [[ -z "$number" ]] && continue
            if [[ -z "${seen[$number]:-}" ]]; then
                seen[$number]=1
                printf '[%s] new issue #%s — %s\n    %s\n' \
                    "$(date +%H:%M:%S)" "$number" "$title" "$url"
            fi
        done <<< "$issues"
    fi

    sleep "$INTERVAL"
done
