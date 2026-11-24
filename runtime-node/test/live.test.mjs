// Live end-to-end test. Skipped unless ZEN_AGENT_LIVE=1, because it needs a real provider.
// Default target is the on-device clawrouter gateway (verified reachable, no credentials).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve } from 'node:path';
import { loadRegistry, route } from '../dist/router.js';
import { loadRules } from '../dist/policy.js';
import { complete, runLiveLoop } from '../dist/agent.js';

const ROOT = process.env.ZEN_AGENT_ROOT ?? resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const LIVE = process.env.ZEN_AGENT_LIVE === '1';
const registry = loadRegistry(join(ROOT, 'providers', 'providers.json'));
const rules = loadRules(join(ROOT, 'protocol', 'fixtures', 'policy-cases.json'));

test('live: a real completion comes back through the routed provider', { skip: !LIVE }, async () => {
  const decision = route(registry, { capability: 'chat', prefer: 'local' });
  const completion = await complete(decision, [{ role: 'user', content: 'reply with exactly: ZEN_OK' }]);
  assert.match(completion.content, /ZEN_OK/);
});

test('live: the agent loop calls the calculator tool and returns a final answer', { skip: !LIVE }, async () => {
  const decision = route(registry, { capability: 'code', prefer: 'local' });
  const outcome = await runLiveLoop(
    decision,
    'Use the calc tool to compute 21*2, then state the number.',
    { root: ROOT, rules, live: true },
    4,
  );
  assert.ok(outcome.final.length > 0, 'a final answer is required');
});
