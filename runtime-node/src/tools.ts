// zen-agent — tools (protocol §6): every call goes through the gate first.
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { evaluate, checkWritePath, normalizeRel } from './policy.js';
import type { ToolContext, ToolResult } from './types.js';

/** Integer arithmetic: + - * / and parentheses. Division truncates toward zero. */
export function calc(expression: string): bigint {
  let i = 0;
  const src = expression.replace(/\s+/g, '');
  const peek = () => src[i];
  function expr(): bigint {
    let v = term();
    while (peek() === '+' || peek() === '-') {
      const op = src[i++];
      const r = term();
      v = op === '+' ? v + r : v - r;
    }
    return v;
  }
  function term(): bigint {
    let v = factor();
    while (peek() === '*' || peek() === '/') {
      const op = src[i++];
      const r = factor();
      if (op === '*') v = v * r;
      else {
        if (r === 0n) throw new Error('division_by_zero');
        v = v / r; // BigInt division truncates toward zero
      }
    }
    return v;
  }
  function factor(): bigint {
    if (peek() === '-') { i++; return -factor(); }
    if (peek() === '(') {
      i++;
      const v = expr();
      if (src[i] !== ')') throw new Error('unbalanced_parenthesis');
      i++;
      return v;
    }
    const start = i;
    while (i < src.length && /[0-9]/.test(src[i])) i++;
    if (i === start) throw new Error(`not_a_number_at_${start}`);
    return BigInt(src.slice(start, i));
  }
  const value = expr();
  if (i !== src.length) throw new Error(`trailing_input_at_${i}`);
  return value;
}

export async function runTool(
  name: string,
  args: Record<string, unknown>,
  ctx: ToolContext,
): Promise<ToolResult> {
  const verdict = evaluate(ctx.rules, name, args);
  if (verdict.decision === 'deny') {
    return { tool: name, ok: false, result: `DENIED:${verdict.code}`, decision: 'deny', code: verdict.code };
  }

  try {
    switch (name) {
      case 'calc': {
        const value = calc(String(args.expression ?? ''));
        return ok(name, value.toString(), verdict.code);
      }
      case 'fs.read': {
        const rel = normalizeRel(String(args.path ?? ''));
        const body = readFileSync(join(ctx.root, rel), 'utf8').replace(/\s+$/, '');
        return ok(name, body, verdict.code);
      }
      case 'fs.write': {
        const rel = checkWritePath(String(args.path ?? ''), ctx.rules.write_roots).path ?? String(args.path);
        const full = join(ctx.root, rel);
        mkdirSync(dirname(full), { recursive: true });
        writeFileSync(full, String(args.content ?? ''));
        return ok(name, `ok:${rel}`, verdict.code);
      }
      case 'text.echo':
        return ok(name, String(args.text ?? ''), verdict.code);
      case 'net.get': {
        const url = String(args.url ?? '');
        if (!ctx.live) return ok(name, 'STUB:no-network-in-fixture-mode', verdict.code);
        const res = await fetch(url);
        const body = (await res.text()).slice(0, 256);
        return ok(name, `${res.status} ${body}`, verdict.code);
      }
      default:
        return { tool: name, ok: false, result: `ERROR:unknown_tool:${name}`, decision: 'allow', code: 'unknown_tool' };
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return { tool: name, ok: false, result: `ERROR:${message}`, decision: 'allow', code: 'tool_error' };
  }
}

function ok(tool: string, result: string, code: string): ToolResult {
  return { tool, ok: true, result, decision: 'allow', code };
}
