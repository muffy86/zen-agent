#!/usr/bin/env bash
# Print ONE credential value, for when you need to paste it into a provider console.
#
#   tools/show-key.sh OPENAI_API_KEY_2
#   bash /workspace/secrets/list-keys.sh          # names + status, no values
#
# This is the only supported way to read a value out of the store. It prints to stdout, so the value
# lands wherever you point it - including, if you ask for it in chat, into that chat's transcript.
# Prefer: copy it to the clipboard yourself, or rotate the key afterwards.
set -euo pipefail

ENV_FILE="${ZEN_AGENT_KEYSTORE:-/workspace/secrets/api-keys.env}"
NAME="${1:-}"
if [ -z "$NAME" ]; then
  echo "usage: show-key.sh NAME        (names: see list-keys.sh)" >&2
  exit 2
fi
if [ ! -f "$ENV_FILE" ]; then
  echo "store missing: $ENV_FILE" >&2
  exit 4
fi
LINE="$(grep -E "^${NAME}=" "$ENV_FILE" || true)"
if [ -z "$LINE" ]; then
  echo "no credential named '$NAME' in the store. Known names:" >&2
  grep -oE '^[A-Z0-9_]+' "$ENV_FILE" | sed 's/^/  /' >&2
  exit 3
fi
printf '%s\n' "${LINE#*=}"
