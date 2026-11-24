#!/usr/bin/env bash
# Full build from a clean checkout. Installs nothing system-wide: every toolchain is project-local
# (npm cache in /tmp, python venv in tools-python/.venv, Gradle home under /opt/gradle-home).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

GRADLE_BIN="${GRADLE_BIN:-/opt/gradle/gradle-8.10.2/bin/gradle}"
export GRADLE_USER_HOME="${GRADLE_USER_HOME:-/opt/gradle-home}"
# npm in PRoot aborts on cache renames across filesystems; a same-filesystem cache fixes it.
NPM_CACHE="${NPM_CACHE:-/tmp/npmcache}"

echo "== node runtime =="
cd "$ROOT/runtime-node"
if [ ! -d node_modules ]; then npm install --cache "$NPM_CACHE" --no-audit --no-fund; fi
./node_modules/.bin/tsc -p tsconfig.json
echo "   built dist/"

echo
echo "== python head =="
cd "$ROOT/tools-python"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install --quiet --no-cache-dir -e ".[dev]"
.venv/bin/python -m zen_agent.cli selftest

echo
echo "== kotlin head =="
cd "$ROOT/core-kotlin"
if [ -x "$GRADLE_BIN" ]; then "$GRADLE_BIN" --no-daemon -q build fatJar; else ./gradlew --no-daemon -q build fatJar; fi
java -jar build/libs/zen-agent-kotlin-core-1.0.0-all.jar selftest

echo
echo "== conformance =="
cd "$ROOT" && bash scripts/conformance.sh

echo
echo "build complete."
