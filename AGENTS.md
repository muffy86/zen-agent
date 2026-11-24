# AGENTS.md — working on zen-agent

Instructions for any agent (or human) changing this repo. They exist because the failure mode of a
polyglot runtime is *drift*: two heads that were equal on Tuesday and disagree on Thursday.

## The five rules

1. **The contract changes first.** Anything that changes behaviour — a routing field, a deny code, a
   result string — is edited in `protocol/agent-protocol.md` and `protocol/fixtures/*.json` **before**
   any implementation. Then all three heads are brought to the new vectors in the same commit.
2. **Never edit a fixture to make a test pass.** If an implementation disagrees with a vector, decide
   which one is wrong and say so in the commit message. Every fixture edit in this repo has a reason
   recorded in the build report.
3. **A new head must pass the same suites before it is described as a head.** The bar is
   `scripts/conformance.sh` plus `scripts/differential.py`, not "it compiles".
4. **No runtime dependency that the others do not need.** Node uses no runtime deps, Python uses only
   the standard library, Kotlin ships as a fat jar with kotlin-stdlib. A convenience library in one
   head is a divergence in behaviour.
5. **Verification claims are labelled.** `verified.reachable: true` in `providers.json` requires a
   live probe with the evidence written down. Everything else says `false` plus why.

## Commands

```bash
./build.sh                          # build all three heads + run the conformance gate
bash scripts/conformance.sh         # 32 vectors x 3 heads, then the 3-head differential
bash scripts/smoke-live.sh          # a real completion through each head (needs a local provider)
cd runtime-node && node --test test/        # node:test
cd tools-python && .venv/bin/python -m pytest
cd core-kotlin && /opt/gradle/gradle-8.10.2/bin/gradle build fatJar
```

## Environment notes (learned the hard way on this device)

- **PRoot + npm**: `npm install` aborts with `ENOENT ... rename .../_cacache/...`. Use a
  same-filesystem cache: `npm install --cache /tmp/npmcache`. `build.sh` already does.
- **Gradle**: `/opt/gradle/gradle-8.10.2/bin/gradle` with `GRADLE_USER_HOME=/opt/gradle-home`.
  `./gradlew` works too, but it re-downloads the distribution.
- **Java**: JDK 17 is present; the Kotlin target is 17.
- **Python**: the venv is `tools-python/.venv`; `pip install --no-cache-dir` avoids the same
  rename problem pip shares with npm on this filesystem.
- **OpenAI tool turns**: an OpenAI-compatible gateway rejects a `role: "tool"` message without a
  non-empty `tool_call_id` (`messages[2]: tool messages must include a non-empty string
  tool_call_id`). The assistant turn must carry the matching `tool_calls` array. All three heads do
  this; do not "simplify" it back to `{role: 'tool', content}`.
- **MCP over HTTP**: `POST`ing `initialize` to `127.0.0.1:8802/mcp` returns the JSON-RPC reply wrapped
  in an SSE `data:` line **and** an `mcp-session-id` header. Omitting that header on the next call
  yields `400 Bad Request: Missing session ID`. All three heads implement the session handshake.
- **Same tool, two answers**: `device_capabilities` reported `shizuku.available: true` from the node
  and kotlin calls and `false` (with `rish present but Shizuku is not running`) from the python call
  minutes apart. That is the gateway's live probe, not a client difference — treat device
  capability fields as momentary, not cached.
- **Run opencode/similar tools inside a real git repo**, never in `/root`: their snapshot feature
  makes the working directory a git work tree and can swallow the home directory.

## Adding a provider

1. Add the entry to `providers/providers.json` with `tier`, `priority`, `auth`, and a capability→model
   map. Keep the priorities meaningful: lower number wins in `quality` mode.
2. Set `verified.reachable` only after probing it, and put the probe evidence in the `evidence` field.
3. If it is OpenAI-compatible, nothing else is needed: all three heads read the same registry.
   If it is not (`anthropic`, `google`, `ollama-native`, `bedrock`, `vertex`), say so in `kind` and
   implement the shape in each head's client — three small functions, no new dependency.
4. Run `bash scripts/conformance.sh` (provider counts and routing vectors must still pass) and
   `node dist/cli.js doctor` to see the new endpoint probed.

## Adding a capability

Capability inference is a table in `Router` in all three heads, in a fixed order
(`voice > vision > math > long > code > reason > chat`). Adding one means: contract §3.1, the table in
three files, and at least one routing vector proving the precedence.
