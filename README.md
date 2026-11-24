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
scripts/             conformance.sh · differential.py · smoke-live.sh
```

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
| Zen inference needs a credential | live probe: `POST opencode.ai/zen/v1/chat/completions` without a key → **429 FreeUsageLimitError** |

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
node dist/cli.js live --capability code --prompt "Use the calc tool to compute 21*2"
java -jar core-kotlin/build/libs/zen-agent-kotlin-core-1.0.0-all.jar live --prompt "reply with exactly: ZEN_OK"
tools-python/.venv/bin/python -m zen_agent.cli live --prompt "reply with exactly: ZEN_OK"
```

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

## Deliberate non-claims

- The 26 paid providers are *catalog entries*. They are wired, they are routable, and they are
  unverified. `providers.json` carries `verified.reachable: false` for each, with the reason.
- Zen's model list is real; Zen *inference* is not available here without a subscription/key (429).
- `lmstudio`, `llama-cpp` and `vllm` have no listener on this device; they are registered because
  they are the local-first targets and cost nothing to include.
- The Kotlin head has no Android UI. It is a JVM library + CLI; the Android surface is a separate
  decision, not an implicit one.

MIT.
