// zen-agent — the policy gate (protocol §5). Runs BEFORE any tool, in every mode.
import { readFileSync } from 'node:fs';
import type { PolicyRules, Verdict } from './types.js';

export function loadRules(path: string): PolicyRules {
  const doc = JSON.parse(readFileSync(path, 'utf8')) as { rules: PolicyRules };
  if (!doc.rules) throw new Error(`policy fixture ${path} has no 'rules' block`);
  return doc.rules;
}

/** Normalise a write path and decide whether it stays inside a configured root. */
export function checkWritePath(raw: string, roots: string[]): Verdict & { path?: string } {
  if (raw.startsWith('/')) return { decision: 'deny', code: 'path_outside_write_root' };
  const out: string[] = [];
  for (const seg of raw.split('/')) {
    if (seg === '' || seg === '.') continue;
    if (seg === '..') {
      // popping past the first segment means the caller tried to leave the sandbox
      if (out.length <= 1) return { decision: 'deny', code: 'path_traversal' };
      out.pop();
      continue;
    }
    out.push(seg);
  }
  if (out.length === 0) return { decision: 'deny', code: 'path_outside_write_root' };
  if (!roots.includes(out[0])) return { decision: 'deny', code: 'path_outside_write_root' };
  return { decision: 'allow', code: 'ok', path: out.join('/') };
}

/** Pure normalisation of a relative read path (no root confinement, only traversal safety). */
export function normalizeRel(raw: string): string {
  const out: string[] = [];
  for (const seg of raw.split('/')) {
    if (seg === '' || seg === '.') continue;
    if (seg === '..') { out.pop(); continue; }
    out.push(seg);
  }
  return out.join('/');
}

export function evaluate(rules: PolicyRules, tool: string, args: Record<string, unknown>): Verdict {  // 1. only tools on the list exist at all — shell.exec is absent on purpose
  if (!rules.enabled_tools.includes(tool)) return { decision: 'deny', code: 'tool_not_enabled' };

  // 2. prompt-injection hygiene: arguments are data, never instructions
  const haystack = JSON.stringify(args ?? {}).toLowerCase();
  if (rules.deny_arg_patterns.some((p) => haystack.includes(p.toLowerCase()))) {
    return { decision: 'deny', code: 'injection_suspected' };
  }

  // 3. filesystem writes stay inside a root, with no traversal
  if (tool === 'fs.write') {
    const v = checkWritePath(String(args?.path ?? ''), rules.write_roots);
    if (v.decision === 'deny') return v;
  }
  // reads are not confined to write roots, but must not climb out of the project
  if (tool === 'fs.read') {
    const raw = String(args?.path ?? '');
    if (raw.startsWith('/')) return { decision: 'deny', code: 'path_outside_write_root' };
    let depth = 0;
    for (const seg of raw.split('/')) {
      if (seg === '' || seg === '.') continue;
      if (seg === '..') { if (depth === 0) return { decision: 'deny', code: 'path_traversal' }; depth--; continue; }
      depth++;
    }
  }

  // 4. network egress is an allow-list of origins
  if (tool === 'net.get') {
    const url = String(args?.url ?? '');
    if (!rules.network_allow.some((origin) => url.startsWith(origin))) {
      return { decision: 'deny', code: 'host_not_allowed' };
    }
  }

  // 5. cheap guard against unbounded work
  if (tool === 'calc') {
    const expr = String(args?.expression ?? '');
    if (expr.length > rules.max_calc_ops) return { decision: 'deny', code: 'expression_too_large' };
  }

  return { decision: 'allow', code: 'ok' };
}
