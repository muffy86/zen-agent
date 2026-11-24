// Golden-vector tests: the same three suites the CLI runs, expressed as real assertions.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve } from 'node:path';
import { loadRegistry, route, inferCapability } from '../dist/router.js';
import { evaluate, loadRules } from '../dist/policy.js';
import { runScriptedLoop } from '../dist/agent.js';
import { calc } from '../dist/tools.js';

const ROOT = process.env.ZEN_AGENT_ROOT ?? resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const FIXTURES = join(ROOT, 'protocol', 'fixtures');
const registry = loadRegistry(join(ROOT, 'providers', 'providers.json'));
const rules = loadRules(join(FIXTURES, 'policy-cases.json'));

function view(d) {
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

const routingCases = JSON.parse(readFileSync(join(FIXTURES, 'routing-cases.json'), 'utf8')).cases;
for (const c of routingCases) {
  test(`routing ${c.id}: ${c.note}`, () => {
    const got = view(route(registry, c.request));
    for (const [key, want] of Object.entries(c.expect)) {
      assert.deepEqual(got[key], want, `${c.id} ${key}`);
    }
  });
}

const policyCases = JSON.parse(readFileSync(join(FIXTURES, 'policy-cases.json'), 'utf8')).cases;
for (const c of policyCases) {
  test(`policy ${c.id}: ${c.tool} -> ${c.expect.decision}/${c.expect.code}`, () => {
    const verdict = evaluate(rules, c.tool, c.args);
    assert.equal(verdict.decision, c.expect.decision);
    assert.equal(verdict.code, c.expect.code);
  });
}

const toolCases = JSON.parse(readFileSync(join(FIXTURES, 'tool-cases.json'), 'utf8')).cases;
for (const c of toolCases) {
  test(`tool loop ${c.id}: ${c.note}`, async () => {
    const got = await runScriptedLoop(c.script, { root: ROOT, rules, live: false });
    assert.deepEqual(got.tools, c.expect.tools);
    assert.deepEqual(got.results, c.expect.results);
    assert.equal(got.final, c.expect.final);
  });
}

test('calculator: integer arithmetic', () => {
  assert.equal(calc('6*7').toString(), '42');
  assert.equal(calc('(2+3)*4').toString(), '20');
  assert.equal(calc('-5 + (10/3)').toString(), '-2'); // division truncates toward zero
  assert.throws(() => calc('1/0'), /division_by_zero/);
});

test('capability inference is ordered voice > vision > math > long > code > reason', () => {
  assert.equal(inferCapability({ prompt: 'transcribe this audio' }), 'voice');
  assert.equal(inferCapability({ prompt: 'read this screenshot' }), 'vision');
  assert.equal(inferCapability({ tags: ['solve the integral'] }), 'math');
  assert.equal(inferCapability({ prompt: 'summarize the pdf' }), 'long');
  assert.equal(inferCapability({ tags: ['refactor kotlin'] }), 'code');
  assert.equal(inferCapability({ prompt: 'plan the strategy' }), 'reason');
  assert.equal(inferCapability({ prompt: 'hello there' }), 'chat');
});

test('the registry never routes to a provider it does not contain', () => {
  const decision = route(registry, { capability: 'chat', providers_available: ['does-not-exist'] });
  assert.equal(decision.status, 'error');
  assert.equal(decision.error_code, 'no_provider_for_capability');
});
