// zen-agent — provider registry + deterministic routing (protocol §2, §3)
import { readFileSync } from 'node:fs';
import type { Capability, Provider, Registry, RouteDecision, RouteRequest, Prefer } from './types.js';

const TIER_RANK: Record<string, number> = { local: 0, free: 1, paid: 2 };

/** Capability inference. First match wins; order is part of the protocol. */
const CAPABILITY_TABLE: Array<[Capability, RegExp]> = [
  ['voice', /\b(voice|speak|audio|tts|transcribe)\b/],
  ['vision', /\b(image|screenshot|photo|vision|ocr)\b/],
  ['math', /\b(math|calcul\w*|arithmetic|integral|equation|solve)\b/],
  ['long', /\b(summar\w*|digest|document|pdf|translat\w*|long-context)\b/],
  ['code', /\b(code|refactor|debug|compile|typescript|kotlin|python|java|script|api|endpoint)\b/],
  ['reason', /\b(reason\w*|plan|analy\w*|strategy|proof|why)\b/],
];

export function inferCapability(req: RouteRequest): string {
  if (req.capability) return req.capability;
  const hay = [...(req.tags ?? []), req.prompt ?? ''].join(' ').toLowerCase();
  for (const [capability, re] of CAPABILITY_TABLE) if (re.test(hay)) return capability;
  return 'chat';
}

export function loadRegistry(path: string): Registry {
  const raw = JSON.parse(readFileSync(path, 'utf8')) as Registry;
  if (!Array.isArray(raw.providers) || raw.providers.length === 0) {
    throw new Error(`registry ${path} has no providers`);
  }
  return raw;
}

function tieBreak(prefer: Prefer, p: Provider): Array<number | string> {
  const tier = TIER_RANK[p.tier] ?? 3;
  if (prefer === 'local') return [p.tier === 'local' ? 0 : 1, p.priority, p.id];
  if (prefer === 'quality') return [p.priority, tier, p.id];
  return [tier, p.priority, p.id];
}

function compareKeys(a: Array<number | string>, b: Array<number | string>): number {
  for (let i = 0; i < a.length; i++) {
    if (a[i] === b[i]) continue;
    return (a[i] as number) < (b[i] as number) ? -1 : 1;
  }
  return 0;
}

/** Credential check: a provider that needs a key it has not been given is not a candidate. */
export function eligible(p: Provider, req: RouteRequest, capability: string): boolean {
  if (req.providers_available && !req.providers_available.includes(p.id)) return false;
  if (req.providers_down?.includes(p.id)) return false;
  if (!(capability in p.models)) return false;
  if (p.auth.key_required && !(p.auth.key_env && (req.env_keys ?? []).includes(p.auth.key_env))) return false;
  if (req.free_only && p.auth.key_required) return false;
  return true;
}

export function route(registry: Registry, req: RouteRequest): RouteDecision {
  const capability = inferCapability(req);
  const prefer: Prefer = req.prefer ?? 'balanced';
  const candidates = registry.providers.filter((p) => eligible(p, req, capability));

  if (candidates.length === 0) {
    return {
      status: 'error',
      capability,
      provider: null,
      model: null,
      endpoint: null,
      kind: null,
      tier: null,
      auth_style: null,
      auth_key_env: null,
      key_required: null,
      prefer,
      fallbacks: [],
      reason: 'no candidate survived the filter set',
      error_code: 'no_provider_for_capability',
      error: { code: 'no_provider_for_capability', message: `no provider can serve capability '${capability}'` },
    };
  }

  const sorted = [...candidates].sort((a, b) => compareKeys(tieBreak(prefer, a), tieBreak(prefer, b)));
  const chosen = sorted[0];
  const fallbacks = sorted.slice(1, 4).map((p) => ({ provider: p.id, model: p.models[capability] }));

  return {
    status: 'ok',
    route_id: `rt-${capability}-${chosen.id}`,
    capability,
    provider: chosen.id,
    model: chosen.models[capability],
    endpoint: chosen.base_url,
    kind: chosen.kind,
    tier: chosen.tier,
    auth_style: chosen.auth.key_required ? chosen.auth.style : 'none',
    auth_key_env: chosen.auth.key_required ? chosen.auth.key_env : null,
    key_required: chosen.auth.key_required,
    prefer,
    fallbacks,
    reason: `tier=${chosen.tier} priority=${chosen.priority} candidates=${candidates.length} prefer=${prefer}`,
    error_code: null,
  };
}
