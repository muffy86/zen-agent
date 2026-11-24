# zen-agent — shared agent protocol v1

One wire contract, three first-class runtimes (`runtime-node`, `tools-python`, `core-kotlin`).
Every runtime must produce **byte-identical routing decisions, policy verdicts and tool results**
for the golden vectors in `protocol/fixtures/`. That equality *is* the test suite
(`scripts/conformance.sh`); it is what makes the polyglot split safe instead of decorative.

## 1. Terms

| Term | Meaning |
|---|---|
| provider | anything that answers an OpenAI-compatible (or native) chat endpoint |
| capability | the *kind of work*, not the model: `chat code reason vision long math voice free embed` |
| route | a deterministic `(provider, model)` choice for a capability + preferences |
| tool | a named, policy-checked function the agent may call |
| policy | the gate that decides allow/deny **before** a tool runs |
| loop | model turn -> tool calls -> results -> model turn, until a final answer |

## 2. Provider registry (`providers/providers.json`)

```jsonc
{
  "id": "clawrouter",
  "kind": "openai-compatible",          // or: anthropic | google | ollama-native | bedrock | vertex
  "base_url": "http://127.0.0.1:8788/v1",
  "auth": { "style": "bearer", "key_required": false, "key_env": null },
  "tier": "local",                       // local | free | paid
  "priority": 10,                        // lower = preferred; ties broken by id
  "verified": { "reachable": true, "checked": "2026-11-23", "evidence": "…" },
  "models": { "chat": "auto:chat", "code": "auto:code", "reason": "auto:reason" }
}
```

`tier_rank`: `local=0, free=1, paid=2, unknown=3`.

## 3. Routing (`route(request)`)

```
candidates = providers where
      (request.providers_available ?: all ids) contains provider.id
  and provider.enabled != false
  and capability in provider.models
  and provider.id not in request.providers_down
  and (provider.auth.key_required == false  or  provider.auth.key_env in request.env_keys)
  and (request.free_only != true  or  provider.auth.key_required == false)
```

`prefer` selects the sort key — this is the **whole** difference between "run locally" and
"buy quality", and it is deliberately boring so that three languages can agree:

| `prefer` | sort key |
|---|---|
| `balanced` (default) | `(tier_rank, priority, id)` |
| `local` | `(is_local ? 0 : 1, priority, id)` |
| `quality` | `(priority, tier_rank, id)` |

Chosen = first candidate; `fallbacks` = next up to 3, as `{provider, model}`.
No candidate -> `{"status":"error","error":{"code":"no_provider_for_capability"}}` (never a guess).

### 3.1 Capability inference

Lowercased haystack of `tags` + `prompt`, first match wins, in this order:

| capability | trigger words |
|---|---|
| `voice` | `voice speak audio tts transcribe` |
| `vision` | `image screenshot photo vision ocr` |
| `math` | `math calcul arithmetic integral equation solve` |
| `long` | `summar digest document pdf translat long-context` |
| `code` | `code refactor debug compile typescript kotlin python java script api endpoint` |
| `reason` | `reason plan analy strategy proof why` |
| `chat` | *(default)* |

## 4. Routing decision

```json
{
  "status": "ok",
  "route_id": "rt-code-clawrouter",
  "capability": "code",
  "provider": "clawrouter",
  "model": "auto:code",
  "endpoint": "http://127.0.0.1:8788/v1",
  "kind": "openai-compatible",
  "tier": "local",
  "auth": { "style": "none", "key_env": null },
  "key_required": false,
  "prefer": "balanced",
  "fallbacks": [ { "provider": "ollama", "model": "qwen2.5-coder:1.5b" } ],
  "reason": "tier=local priority=10 candidates=3 prefer=balanced"
}
```

`reason` is human-facing and **not** asserted; every other field is.

## 5. Policy gate (`evaluate(tool, args)`)

Evaluated in this order, first verdict wins. Verdict = `{"decision":"allow"|"deny","code":"…"}`.

| # | check | deny code |
|---|---|---|
| 1 | tool present in the enabled tool list | `tool_not_enabled` |
| 2 | no `deny_arg_patterns` match in the JSON-serialised args | `injection_suspected` |
| 3 | `fs.write` path, normalised, stays inside a configured write root | `path_traversal` (if `..` escapes) / `path_outside_write_root` |
| 4 | `net.get` host is in `network_allow` (scheme+host prefix match) | `host_not_allowed` |
| 5 | `calc` expression length <= `max_calc_ops` | `expression_too_large` |
| 6 | otherwise | `allow` / `ok` |

Reads are **not** restricted to write roots — the agent must be able to read the project it is
working in. `fs.read` is normalised for traversal only (`path_traversal` if `..` climbs past the
first segment) and then allowed.

`auth_style` is the **effective** mode: the provider's style when a credential is required, and
`none` when the provider works without one. `key_required` carries the underlying fact, so an
optional-credential provider (Zen: catalog free, inference rate-limited) is never misread as
"authenticated".

Root is `{root}` = the repo root. `protocol/fixtures/policy-cases.json` is the golden set.

## 6. Tool result envelope

```json
{ "tool": "calc", "ok": true,  "result": "42",  "decision": "allow", "code": "ok" }
{ "tool": "fs.write", "ok": false, "result": "DENIED:path_outside_write_root", "decision": "deny", "code": "path_outside_write_root" }
```

A denial is **data, not an exception**: the loop keeps going and the model is told what was refused.
Result text for `calc` is a canonical decimal string; for `fs.read` the file content stripped of
trailing whitespace; for `net.get` the response body prefix; for `text.echo` the text verbatim.

## 7. The loop

```
turn 1: model -> {tool_call{name,args}} | {final}
execute scripted/live tool calls through the gate, append results, repeat
stop when: a `final` arrives, or max_turns is hit
```

`tools` names in v1: `calc`, `fs.read`, `fs.write`, `text.echo`, `net.get` (plus `shell.exec`,
which exists in the policy table precisely so that it can be **denied** by default).

## 8. Non-negotiable rules

1. No runtime may invent a provider that the registry does not contain.
2. No tool runs before the gate returns `allow` — including in fixture mode, so tests cover the gate.
3. Golden vectors are shared, not per-language: a fix in one fixture must be satisfied by all three.
4. A live smoke test must prove at least one real completion end to end (`scripts/smoke-live.sh`).
