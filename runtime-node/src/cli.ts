#!/usr/bin/env node
// zen-agent — CLI + golden-vector conformance harness (protocol §8.3).
import { existsSync, readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { join, resolve } from 'node:path';
import { route, loadRegistry, inferCapability } from './router.js';
import { loadRules, evaluate } from './policy.js';
import { runTool } from './tools.js';
import { runScriptedLoop, runLiveLoop } from './agent.js';
import { MemoryStore } from './memory.js';
import { McpStdioClient, McpHttpClient } from './mcp.js';
import type { RouteDecision, RouteRequest, ScriptTurn, ToolContext } from './types.js';

import { fileURLToPath } from 'node:url';
import { dirname } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = process.env.ZEN_AGENT_ROOT ?? resolve(HERE, '..', '..'); // dist/ -> runtime-node/ -> repo root
const REGISTRY = join(ROOT, 'providers', 'providers.json');
const FIXTURES = join(ROOT, 'protocol', 'fixtures');

function argsOf(argv: string[]): Record<string, string | boolean> {
  const out: Record<string, string | boolean> = {};
  for (let i = 0; i < argv.length; i++) {
    const token = argv[i];
    if (!token.startsWith('--')) {
      if (out._ === undefined) out._ = token; // first positional
      continue;
    }
    const key = token.slice(2);
    const next = argv[i + 1];
    if (next === undefined || next.startsWith('--')) out[key] = true;
    else { out[key] = next; i++; }
  }
  return out;
}

function json(value: unknown): void { process.stdout.write(`${JSON.stringify(value, null, 2)}\n`); }

function requestFrom(args: Record<string, string | boolean>): RouteRequest {
  const req: RouteRequest = {};
  if (typeof args.capability === 'string') req.capability = args.capability;
  if (typeof args.prompt === 'string') req.prompt = args.prompt;
  if (typeof args.tags === 'string') req.tags = args.tags.split(',');
  if (typeof args.prefer === 'string') req.prefer = args.prefer as RouteRequest['prefer'];
  if (typeof args.available === 'string') req.providers_available = args.available.split(',');
  if (typeof args.down === 'string') req.providers_down = args.down.split(',');
  if (typeof args.env === 'string') req.env_keys = args.env.split(',');
  if (args['free-only'] === true) req.free_only = true;
  return req;
}

/** The exact projection every runtime must agree on. */
export function assertableView(d: RouteDecision): Record<string, unknown> {
  return {
    status: d.status,
    route_id: d.route_id ?? null,
    capability: d.capability,
    provider: d.provider,
    model: d.model ?? null,
    tier: d.tier ?? null,
    auth_style: d.auth_style ?? null,
    key_required: d.key_required ?? null,
    fallback_providers: (d.fallbacks ?? []).map((f) => f.provider),
    error_code: d.error_code,
  };
}

function equal(a: unknown, b: unknown): boolean { return JSON.stringify(a) === JSON.stringify(b); }

async function conformance(): Promise<number> {
  const registry = loadRegistry(REGISTRY);
  let checks = 0;
  let failures = 0;
  const report = (suite: string, id: string, problems: string[]) => {
    checks++;
    if (problems.length === 0) { console.log(`  PASS ${suite}/${id}`); return; }
    failures++;
    console.log(`  FAIL ${suite}/${id}: ${problems.join('; ')}`);
  };

  console.log(`routing (${registry.providers.length} providers in registry)`);
  const routing = JSON.parse(readFileSync(join(FIXTURES, 'routing-cases.json'), 'utf8')) as {
    cases: Array<{ id: string; request: RouteRequest; expect: Record<string, unknown> }>;
  };
  for (const c of routing.cases) {
    const view = assertableView(route(registry, c.request));
    const problems: string[] = [];
    for (const [key, want] of Object.entries(c.expect)) {
      if (!equal(view[key], want)) problems.push(`${key}: want ${JSON.stringify(want)} got ${JSON.stringify(view[key])}`);
    }
    report('routing', c.id, problems);
  }

  const policy = JSON.parse(readFileSync(join(FIXTURES, 'policy-cases.json'), 'utf8')) as {
    rules: ToolContext['rules'];
    cases: Array<{ id: string; tool: string; args: Record<string, unknown>; expect: { decision: string; code: string } }>;
  };
  console.log('policy');
  for (const c of policy.cases) {
    const verdict = evaluate(policy.rules, c.tool, c.args);
    const problems: string[] = [];
    if (verdict.decision !== c.expect.decision) problems.push(`decision: want ${c.expect.decision} got ${verdict.decision}`);
    if (verdict.code !== c.expect.code) problems.push(`code: want ${c.expect.code} got ${verdict.code}`);
    report('policy', c.id, problems);
  }

  const toolCases = JSON.parse(readFileSync(join(FIXTURES, 'tool-cases.json'), 'utf8')) as {
    cases: Array<{ id: string; script: ScriptTurn[]; expect: { tools: string[]; results: string[]; final: string } }>;
  };
  console.log('tool loop');
  for (const c of toolCases.cases) {
    const outcome = await runScriptedLoop(c.script, { root: ROOT, rules: policy.rules, live: false });
    const problems: string[] = [];
    if (!equal(outcome.tools, c.expect.tools)) problems.push(`tools: want ${JSON.stringify(c.expect.tools)} got ${JSON.stringify(outcome.tools)}`);
    if (!equal(outcome.results, c.expect.results)) problems.push(`results: want ${JSON.stringify(c.expect.results)} got ${JSON.stringify(outcome.results)}`);
    if (outcome.final !== c.expect.final) problems.push(`final: want ${JSON.stringify(c.expect.final)} got ${JSON.stringify(outcome.final)}`);
    report('tools', c.id, problems);
  }

  console.log(`\nconformance (node): ${checks - failures}/${checks} vectors pass`);
  return failures;
}

async function doctor(): Promise<number> {
  const registry = loadRegistry(REGISTRY);
  let reachable = 0;
  for (const p of registry.providers) {
    const url = p.kind === 'ollama-native' ? `${p.base_url}/api/tags` : `${p.base_url}/models`;
    let status = 'unreachable';
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(4000) });
      status = String(res.status);
      if (res.ok) reachable++;
    } catch (err) {
      status = `error:${(err as Error).name}`;
    }
    console.log(`${p.id.padEnd(16)} ${p.tier.padEnd(6)} ${status.padEnd(12)} ${url}`);
  }
  console.log(`\nreachable: ${reachable}/${registry.providers.length}`);
  return 0;
}

async function main(): Promise<void> {
  const [command, ...rest] = process.argv.slice(2);
  const args = argsOf(rest);
  switch (command) {
    case 'providers': {
      const registry = loadRegistry(REGISTRY);
      if (args.json) { json(registry.providers.map((p) => ({ id: p.id, tier: p.tier, kind: p.kind, verified: p.verified?.reachable ?? false }))); break; }
      for (const p of registry.providers) {
        console.log(`${p.verified?.reachable ? '●' : '○'} ${p.id.padEnd(16)} ${p.tier.padEnd(6)} ${p.priority.toString().padStart(3)} ${p.kind.padEnd(18)} ${p.base_url}`);
      }
      break;
    }
    case 'route': {
      const decision = route(loadRegistry(REGISTRY), requestFrom(args));
      if (args.json) json(decision);
      else console.log(`${decision.status} ${decision.route_id ?? decision.error_code} -> ${decision.provider ?? '-'} / ${decision.model ?? '-'} (fallbacks: ${decision.fallbacks.map((f) => f.provider).join(', ') || 'none'})`);
      process.exitCode = decision.status === 'ok' ? 0 : 3;
      break;
    }
    case 'infer': {
      console.log(inferCapability({ prompt: String(args.prompt ?? ''), tags: typeof args.tags === 'string' ? args.tags.split(',') : [] }));
      break;
    }
    case 'tool': {
      const rules = loadRules(join(FIXTURES, 'policy-cases.json'));
      const toolArgs = JSON.parse(String(args.args ?? '{}')) as Record<string, unknown>;
      const r = await runTool(String(args._ ?? args.name ?? ''), toolArgs, { root: ROOT, rules, live: args.live === true });      json(r);
      break;
    }
    case 'loop': {
      const rules = loadRules(join(FIXTURES, 'policy-cases.json'));
      const script = JSON.parse(String(args.script ?? '[]')) as ScriptTurn[];
      json(await runScriptedLoop(script, { root: ROOT, rules, live: false }));
      break;
    }
    case 'live': {
      const registry = loadRegistry(REGISTRY);
      const req = requestFrom(args);
      const decision = route(registry, req);
      const apiKey = decision.auth_key_env ? process.env[decision.auth_key_env] : undefined;
      if (decision.status !== 'ok') { console.error(`no route: ${decision.error_code}`); process.exit(2); }
      const outcome = await runLiveLoop(decision, String(args.prompt ?? 'reply with exactly: ZEN_OK'), { root: ROOT, rules: loadRules(join(FIXTURES, 'policy-cases.json')), live: true, apiKey });
      new MemoryStore(join(ROOT, 'memory', 'memory.jsonl')).append({ kind: 'answer', route: decision.route_id, tools: outcome.tools, final: outcome.final });
      console.log(JSON.stringify({ route: decision.route_id, provider: decision.provider, model: decision.model, tools: outcome.tools, results: outcome.results, final: outcome.final }, null, 2));
      break;
    }
    case 'mcp': {
      // auto-detect the transport: an http(s) target speaks HTTP MCP, anything else is a command
      const target = String(args._ ?? '');
      if (target === '') { console.error('usage: zen-agent mcp <url|command> [--call tool --args json]'); process.exitCode = 2; break; }
      const client = target.startsWith('http')
        ? new McpHttpClient(target, args.header ? { authorization: String(args.header) } : {})
        : new McpStdioClient(target, typeof args.arg === 'string' ? [args.arg] : []);
      await client.start();
      if (typeof args.call === 'string') {
        const result = await client.callTool(args.call, JSON.parse(String(args.args ?? '{}')) as Record<string, unknown>);
        console.log(JSON.stringify(result, null, 2));
      } else {
        const tools = await client.listTools();
        for (const tool of tools) console.log(`${tool.name.padEnd(28)} ${(tool.description ?? '').slice(0, 90)}`);
        console.log(`\n${tools.length} tools from ${target}`);
      }
      client.close();
      break;
    }
    case 'memory': {
      json(new MemoryStore(join(ROOT, 'memory', 'memory.jsonl')).recall(String(args.query ?? '')));
      break;
    }
    case 'conformance': {
      process.exitCode = (await conformance()) === 0 ? 0 : 1;
      break;
    }
    case 'doctor': {
      process.exitCode = await doctor();
      break;
    }
    case 'selftest': {
      // one call that proves the install is alive without touching a model
      const registry = loadRegistry(REGISTRY);
      const decision = route(registry, { capability: 'code', prefer: 'local' });
      console.log(`registry: ${registry.providers.length} providers`);
      console.log(`route:    ${decision.route_id} -> ${decision.model} @ ${decision.endpoint}`);
      console.log(`node:     ${process.version}`);
      console.log(`root:     ${ROOT}`);
      const echoed = execFileSync('node', ['--version'], { encoding: 'utf8' }).trim();
      console.log(`spawn ok: ${echoed}`);
      break;
    }
    default:
      console.log(readFileSync(join(ROOT, 'runtime-node', 'USAGE.txt'), 'utf8'));
  }
}

if (!existsSync(REGISTRY) && (process.argv[2] ?? '') !== 'help') {
  console.error(`zen-agent: registry not found at ${REGISTRY} — set ZEN_AGENT_ROOT to the repo root`);
  process.exit(2);
}
await main();
