#!/usr/bin/env bash
# One command that proves all three heads satisfy the shared golden vectors, then proves
# the three heads agree with each other on the same requests.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KOTLIN_JAR="$ROOT/core-kotlin/build/libs/zen-agent-kotlin-core-1.0.0-all.jar"
status=0

echo "== vectors: node =="
(cd "$ROOT/runtime-node" && node dist/cli.js conformance) || status=1

echo
echo "== vectors: python =="
"$ROOT/tools-python/.venv/bin/python" -m zen_agent.cli conformance || status=1

echo
echo "== vectors: kotlin =="
java -jar "$KOTLIN_JAR" conformance || status=1

echo
echo "== differential: the three heads against each other =="
python3 "$ROOT/scripts/differential.py" || status=1

echo
if [ "$status" -eq 0 ]; then
  echo "CONFORMANCE: PASS (all heads satisfy every golden vector and agree with each other)"
else
  echo "CONFORMANCE: FAIL"
fi
exit "$status"
