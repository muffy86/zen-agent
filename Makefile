GRADLE_BIN ?= /opt/gradle/gradle-8.10.2/bin/gradle
export GRADLE_USER_HOME ?= /opt/gradle-home
PY   := tools-python/.venv/bin/python
KJAR := core-kotlin/build/libs/zen-agent-kotlin-core-1.0.0-all.jar

.PHONY: all node python kotlin test conformance differential live doctor dist clean help

all: node python kotlin conformance

help:
	@echo "make all | node | python | kotlin | test | conformance | differential | live | doctor | dist | clean"

node:
	cd runtime-node && [ -d node_modules ] || npm install --cache /tmp/npmcache --no-audit --no-fund
	cd runtime-node && ./node_modules/.bin/tsc -p tsconfig.json

python:
	[ -d tools-python/.venv ] || python3 -m venv tools-python/.venv
	$(PY) -m pip install --quiet --no-cache-dir -e "tools-python[dev]"

kotlin:
	cd core-kotlin && $(GRADLE_BIN) --no-daemon -q build fatJar

test: node kotlin
	cd runtime-node && node --test test/
	$(PY) -m pytest tools-python
	cd core-kotlin && $(GRADLE_BIN) --no-daemon -q test

conformance:
	bash scripts/conformance.sh

differential:
	python3 scripts/differential.py

live:
	bash scripts/smoke-live.sh

doctor:
	cd runtime-node && node dist/cli.js doctor

dist: all
	@mkdir -p ../dist/zen-agent-1.0.0/python
	cd runtime-node && npm pack --pack-destination ../dist/zen-agent-1.0.0
	cd tools-python && .venv/bin/python -m build --outdir ../../dist/zen-agent-1.0.0/python .
	cp $(KJAR) ../dist/zen-agent-1.0.0/
	bash scripts/package.sh

clean:
	rm -rf runtime-node/dist core-kotlin/build tools-python/build tools-python/*.egg-info
