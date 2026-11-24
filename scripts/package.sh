#!/usr/bin/env bash
# Bundle the source tree and checksum every artifact in ../dist/zen-agent-<version>/.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${VERSION:-1.0.0}"
OUT="$(cd "$ROOT/.." && pwd)/dist/zen-agent-$VERSION"
mkdir -p "$OUT"

echo "== source bundle =="
BUNDLE="$OUT/zen-agent-$VERSION-src.zip"
rm -f "$BUNDLE"
cd "$ROOT"
zip -qr "$BUNDLE" . \
  -x 'runtime-node/node_modules/*' 'runtime-node/dist/*' 'core-kotlin/build/*' 'core-kotlin/.gradle/*' \
     'tools-python/.venv/*' 'tools-python/build/*' 'tools-python/*.egg-info/*' 'memory/memory.jsonl' \
     '.git/*' 'out/*' '*.tgz'
echo "   $(du -h "$BUNDLE" | cut -f1)  $BUNDLE"

echo
echo "== checksums =="
cd "$OUT"
sha256sum ./*.tgz ./*.jar ./python/* 2>/dev/null | tee sha256sums.txt
echo
echo "artifacts in $OUT"
ls -la "$OUT"
