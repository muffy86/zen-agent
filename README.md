# zen-agent

A polyglot agentic runtime. **One provider registry, one policy gate, three first-class
implementations** — TypeScript, Python and Kotlin — proven equal by shared golden vectors.

The design bet: an agent that must live on a phone, in a container and in CI cannot be one language.
So the *contract* is the product (`protocol/`), and each head is an implementation of it. If the
heads ever disagree about a routing decision or a policy verdict, the build fails — that check is
`scripts/differential.py`, and it runs three real binaries, not three mocks.

```
protocol/            the contract: agent-protocol.md + schemas + golden vectors (shared, not per-language)
providers/           providers.json — 32 providers, capability→model map, tier, priority, live verification
runtime-node/        TypeScript head   (CLI: zen-agent)        tests: node:test
tools-python/        Python head       (CLI: zen-agent-py)     tests: pytest
core-kotlin/         Kotlin/JVM head   (CLI: fat jar)          tests: kotlin.test
scripts/             conformance.sh · differential.py · smoke-live.sh · package.sh
```

Components per head — stated per head, because a claim of symmetry that is not tested is decoration:

| Component | node | python | kotlin |
|---|---|---|---|
| provider registry + routing + gate + tools | ● | ● | ● |
| agent loop (scripted + live, OpenAI & ollama shapes) | ● | ● | ● |
| portable memory (JSONL + lexical recall) | ● | ● | ● |
| MCP client over stdio | ● | ● | – |
| MCP client over HTTP+SSE (session handshake) | ● | ● | ● |

The four `●` rows in column one are covered by the shared golden vectors; the MCP rows are not
vectors but were run live against the device gateway, on all three heads.

## Where this lives

| | |
|---|---|
| Repository | https://github.com/muffy86/zen-agent — public |
| CI | four jobs on every push (`node head`, `python head`, `kotlin head`, `the three heads must agree`) — all green |
| Published package | `@muffy86/zen-agent@1.0.1` on GitHub Packages. **Currently private**: GitHub Packages sets package visibility per package, at publish time, and does not inherit a later change to the repository. Flip it once under the package's settings → Danger Zone → Change visibility |
| Released assets | fat jar (`zen-agent-kotlin-core-1.0.0-all.jar`), python wheel/sdist, npm tarball, source bundle — built and checksummed under `../dist/zen-agent-1.0.0/` |
| CI artifacts | every tag run uploads `zen-agent-python-dist` and `zen-agent-kotlin-jar` |

## What is verified, and how

| Claim | Evidence |
|---|---|
| 32 providers in one registry | `providers/providers.json`, counts asserted by every head |
| All three heads satisfy every golden vector | `node/py/kotlin`: **32/32 vectors pass** each (15 routing, 12 policy, 5 tool-loop) |
| The three heads agree with each other | `scripts/differential.py`: **15/15 requests identical** across three separate processes, `reason` string included |
| A real model answers through every head | `scripts/smoke-live.sh`: **PASS** — node, python and kotlin each got a completion from clawrouter `auto:chat` |
| The agentic loop really calls a tool | live run, all three heads: prompt `compute 21*2 with calc` → tool `calc` → result `42` → final `42` |
| The gate really refuses things | `policy/p04`: `/etc/passwd` → `DENIED:path_outside_write_root`; `p08`: injection text → `injection_suspected`; `p09`: `shell.exec` → `tool_not_enabled` |
| Provider catalogs are real, not guessed | Zen: **108 model ids** fetched live; clawrouter: 22; Ollama: 13 installed models |
| Zen works from this client with a Console key | personal key `zen-agent (kelivo)`, scope *Models: Request*: `GET opencode.ai/inference/v1/models` → **200 (77 ids)**; `POST /inference/openai/v1/chat/completions` → **200** for `glm-5.3`, `glm-5.3-flash`, `deepseek-v4.1-flash`, `kimi-k3`, `gemini-3.8-flash`; all three heads complete a live run through it |
| Zen's free ids are refused to non-OpenCode clients | `*-free` ids → **429 FreeUsageLimitError** with a valid key present (vendor doc: HTTP 403 from other clients). Paid/Go ids are the only ones that work here |
| Zen usage is billed, not free | every measured call reported `billing_source: balance` — charged to Console credit (glm-5.3-flash $0.0000494, deepseek-v4.1-flash $0.000017, glm-5.3 $0.00014264) |
| The MCP component reaches the device's real tool bus | all three heads list **19 device tools** (`/mcp` on 8802) and **23 browser tools** (8801), and each called `device_capabilities` successfully |
| Artifacts install clean | wheel in a fresh venv: **32/32 vectors**; tarball in a fresh npm dir: works; fat jar: standalone |
| The same gate passes in the cloud, and publishes | GitHub Actions: 4 jobs green on `main`, 5/5 on tag `v1.0.0`/`v1.0.1` including `publish packages` → `+ @muffy86/zen-agent@1.0.1` |
| Real providers behind real keys | `clawrouter` (local), `opencode-zen` (Console key: glm-5.3-flash, measured $0.0000494/call), `groq` (openai/gpt-oss-120b), `ollama` (local) — each completes a live run in all three heads |

## Quickstart

```bash
./build.sh                       # node + python + kotlin, then the full conformance run
bash scripts/conformance.sh      # vectors, three heads, then the differential
bash scripts/smoke-live.sh       # a real completion through each head
```

Route something:

```bash
cd runtime-node && node dist/cli.js route --capability code --prefer local --json
cd runtime-node && node dist/cli.js route --prompt "summarize this 400 page pdf" --json
cd runtime-node && node dist/cli.js doctor        # live-probe every provider endpoint
cd runtime-node && node dist/cli.js providers     # ● verified reachable, ○ catalog-only
```

Talk to a model through the routed provider, whole loop included:

```bash
cd runtime-node && node dist/cli.js live --capability code --prompt "Use the calc tool to compute 21*2"
java -jar core-kotlin/build/libs/zen-agent-kotlin-core-1.0.0-all.jar live --prompt "reply with exactly: ZEN_OK"
tools-python/.venv/bin/python -m zen_agent.cli live --prompt "reply with exactly: ZEN_OK"
```

### Driving the device's own tool bus

The gateway on this machine speaks MCP over HTTP, so the MCP component has both transports:

```bash
node dist/cli.js mcp http://127.0.0.1:8802/mcp                                   # 19 Android-control tools
node dist/cli.js mcp http://127.0.0.1:8801/mcp/                                  # 23 browser-control tools
node dist/cli.js mcp http://127.0.0.1:8802/mcp --call device_capabilities --args '{}'
node dist/cli.js mcp /path/to/mcp-server --arg --whatever                       # stdio servers too (node, python)
```

Two things the gateway enforces and this client honours: the `mcp-session-id` header returned by
`initialize` must be echoed on every later call, and each JSON-RPC reply arrives inside an SSE
`data:` line rather than as a bare body.

## Routing in one table

`capability` is the *kind of work*, not a model: `chat code reason vision long math voice free embed`.
Candidates are the providers that (a) are available, (b) actually have a model for that capability,
and (c) either need no credential or have one present. Then one sort key decides:

| `prefer` | sort key | meaning |
|---|---|---|
| `balanced` (default) | `(tier_rank, priority, id)` | local, then free, then paid |
| `local` | `(is_local, priority, id)` | locality above everything |
| `quality` | `(priority, tier_rank, id)` | your hand-ordered provider preference |

No candidate ⇒ `status: error`, `no_provider_for_capability`. Never a silent default.

## Provider tiers on this device

| Tier | Providers | Status |
|---|---|---|
| local | `clawrouter` (127.0.0.1:8788), `ollama` (11434), `lmstudio`, `llama-cpp`, `vllm` | first two verified reachable, no credential |
| free | `opencode-zen` (108 ids) | catalog verified; inference rate-limited without `OPENCODE_ZEN_API_KEY` |
| paid | 26 more: openrouter, openai, anthropic, google-gemini, xai, deepseek, groq, cerebras, moonshot-kimi, zai-glm, minimax, nous, mistral, together, fireworks, perplexity, nvidia-nim, sambanova, nebius, siliconflow, hyperbolic, aihubmix, github-models, azure-openai, aws-bedrock, google-vertex | catalog-only: **no key on this device, so none of these is claimed to work** |

`./cli.js doctor` is the command that turns that table into fresh evidence.

## The gate

Every tool call goes through `protocol/agent-protocol.md §5` before it runs, in fixture mode as well
as live mode — that is why the tests cover the gate instead of trusting it:

1. tool on the enabled list (so `shell.exec` can be denied by construction)
2. argument hygiene against injection patterns (arguments are data, never instructions)
3. `fs.write` confined to a write root, `..` escapes refused
4. `net.get` egress against an origin allow-list
5. `calc` size bound; then allow

A denial is **data**: the loop keeps going and the model is told what was refused.

## Zen / Console — the parts that are easy to get wrong

- **Base URL is `https://opencode.ai/inference/openai/v1`**, not `/zen/v1` (the vendor's Inference API
  doc). `/zen/v1` still answers a model list unauthenticated, which is a good way to mistake a catalog
  for a working route.
- **A key is not entitlement, and entitlement is not the same as free.** Free-tier chat models are
  OpenCode-client-only; another client gets a refusal. Paid models or a Go plan are what work here.
- **Other clients are billed to balance.** Measured on every call: `billing_source: balance`.
- The key lives in `.env` (`OPENCODE_ZEN_API_KEY`), created 2026-11-24, **expires 2027-02-23**.

## Deliberate non-claims

- The 26 paid providers are *catalog entries*. They are wired, they are routable, and they are
  unverified. `providers.json` carries `verified.reachable: false` for each, with the reason.
- Zen's model list is real; Zen *inference* is not available here without a subscription/key (429).
- `lmstudio`, `llama-cpp` and `vllm` have no listener on this device; they are registered because
  they are the local-first targets and cost nothing to include.
- The Kotlin head has no Android UI. It is a JVM library + CLI; the Android surface is a separate
  decision, not an implicit one.

MIT.
