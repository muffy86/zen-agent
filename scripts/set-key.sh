#!/usr/bin/env bash
# Put a credential into .env without ever echoing it.
#
#   scripts/set-key.sh OPENCODE_ZEN_API_KEY          # reads the secret from stdin
#   pbpaste | scripts/set-key.sh NODE_AUTH_TOKEN     # macOS
#   termux-clipboard-get | scripts/set-key.sh NODE_AUTH_TOKEN   # Termux
#
# The value is written straight to .env (chmod 600, gitignored). It is never printed, never logged,
# and never passed as a command-line argument (arguments show up in `ps`).
set -euo pipefail

NAME="${1:-}"
if [ -z "$NAME" ]; then
  echo "usage: scripts/set-key.sh ENV_VAR_NAME   (secret on stdin)" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"

VALUE="$(cat)"
VALUE="${VALUE//$'\r'/}"
VALUE="${VALUE//$'\n'/}"

if [ -z "$VALUE" ]; then
  echo "refusing to write an empty value for $NAME" >&2
  exit 3
fi

touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

TMP="$(mktemp "$ROOT/.env.XXXXXX")"
grep -v -E "^[[:space:]]*${NAME}=" "$ENV_FILE" > "$TMP" 2>/dev/null || true
printf '%s=%s\n' "$NAME" "$VALUE" >> "$TMP"
cat "$TMP" > "$ENV_FILE"          # same inode: keeps ownership and the 600 mode
rm -f "$TMP"

echo "wrote $NAME (${#VALUE} chars) to $ENV_FILE — value not echoed"
echo "check with: node runtime-node/dist/cli.js env"
