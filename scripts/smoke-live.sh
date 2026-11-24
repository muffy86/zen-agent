#!/usr/bin/env bash
# Live end-to-end: a real model must answer through every head.
# Default target is the on-device clawrouter gateway (verified reachable, no credentials).
# For OpenCode Zen: export OPENCODE_ZEN_API_KEY=... and add --available opencode-zen.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KOTLIN_JAR="$ROOT/core-kotlin/build/libs/zen-agent-kotlin-core-1.0.0-all.jar"
PROMPT="${PROMPT:-reply with exactly: ZEN_OK}"
EXPECT="${EXPECT:-ZEN_OK}"
CAPABILITY="${CAPABILITY:-chat}"
status=0

probe() {
  local name="$1"; shift
  local output
  output="$("$@" 2>&1)"
  if grep -q "$EXPECT" <<<"$output"; then
    echo "PASS  $name (model answered through ${CAPABILITY})"
    grep -o '"model": "[^"]*"' <<<"$output" | head -1 | sed 's/^/      served by /'
  else
    echo "FAIL  $name"
    echo "$output" | tail -6 | sed 's/^/      /'
    status=1
  fi
}

echo "live smoke: prompt='$PROMPT' expect='$EXPECT'"
probe node bash -c "cd '$ROOT/runtime-node' && node dist/cli.js live --capability $CAPABILITY --prompt '$PROMPT' --prefer local"
probe python "$ROOT/tools-python/.venv/bin/python" -m zen_agent.cli live --capability "$CAPABILITY" --prompt "$PROMPT" --prefer local
probe kotlin java -jar "$KOTLIN_JAR" live --capability "$CAPABILITY" --prompt "$PROMPT" --prefer local

echo
if [ "$status" -eq 0 ]; then echo "LIVE SMOKE: PASS (all three heads got a real completion)"; else echo "LIVE SMOKE: FAIL"; fi
exit "$status"
