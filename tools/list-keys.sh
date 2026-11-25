#!/usr/bin/env bash
# List credential NAMES and their audit status. Never prints a value.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ZEN_AGENT_KEYSTORE:-/workspace/secrets/api-keys.env}"
STATUS_FILE="$(dirname "$ENV_FILE")/KEY-STATUS.md"

printf "%-28s %-12s %s\n" "CREDENTIAL" "STATUS" "(value: bash show-key.sh NAME)"
printf "%-28s %-12s %s\n" "--------------------------" "------------" "-----------------------------------"
for name in $(grep -oE '^[A-Z0-9_]+' "$ENV_FILE"); do
  status="$(grep -F "\`$name\`" "$STATUS_FILE" 2>/dev/null | head -1 | cut -d'|' -f3 | tr -d ' *')"
  [ -z "$status" ] && status="UNAUDITED"
  printf "%-28s %-12s %s\n" "$name" "$status" ""
done
echo
echo "count: $(grep -cE '^[A-Z0-9_]+=' "$ENV_FILE") credentials stored in $ENV_FILE"
echo "audit: python3 $DIR/audit-keys.py   (re-checks liveness, rewrites KEY-STATUS.md)"
