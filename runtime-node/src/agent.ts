// zen-agent — the agent loop (protocol §7): scripted (golden vectors) and live (real provider).
import { runTool } from './tools.js';
import type { LoopOutcome, RouteDecision, ScriptTurn, ToolContext } from './types.js';

export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
}

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
  /** required on `tool` turns: OpenAI-compatible gateways reject a tool result without it */
  tool_call_id?: string;
  name?: string;
  /** required on the assistant turn that requested the calls, so the results can be matched */
  tool_calls?: Array<{ id: string; type: 'function'; function: { name: string; arguments: string } }>;
}

export interface Completion {
  content: string;
  tool_calls: ToolCall[];
  raw: unknown;
}

/**
 * Deterministic loop over a scripted transcript. Used by every runtime's conformance suite:
 * the gate and the tool implementations are real, only the model is a script.
 */
export async function runScriptedLoop(script: ScriptTurn[], ctx: ToolContext): Promise<LoopOutcome> {
  const tools: string[] = [];
  const results: string[] = [];
  let final = '';
  for (const turn of script) {
    if (turn.tool_call) {
      const { name, args } = turn.tool_call;
      const r = await runTool(name, args ?? {}, ctx);
      tools.push(name);
      results.push(r.result);
      continue;
    }
    if (typeof turn.final === 'string') {
      final = turn.final;
      break;
    }
  }
  return { tools, results, final };
}

function authHeaders(decision: RouteDecision, apiKey: string | undefined): Record<string, string> {
  const headers: Record<string, string> = { 'content-type': 'application/json' };
  if (decision.auth_style === 'bearer' && apiKey) headers.authorization = `Bearer ${apiKey}`;
  if (decision.auth_style === 'x-api-key' && apiKey) headers['x-api-key'] = apiKey;
  if (decision.auth_style === 'api-key' && apiKey) headers['api-key'] = apiKey;
  return headers;
}

const TOOL_SCHEMA = [
  { type: 'function', function: { name: 'calc', description: 'Integer arithmetic: + - * / and parentheses.', parameters: { type: 'object', properties: { expression: { type: 'string' } }, required: ['expression'] } } },
  { type: 'function', function: { name: 'fs.read', description: 'Read a file inside the sandbox root.', parameters: { type: 'object', properties: { path: { type: 'string' } }, required: ['path'] } } },
  { type: 'function', function: { name: 'fs.write', description: 'Write a file inside a configured write root.', parameters: { type: 'object', properties: { path: { type: 'string' }, content: { type: 'string' } }, required: ['path', 'content'] } } },
];

/** One model turn against the routed provider. Ollama speaks its native shape; everything else OpenAI. */
export async function complete(
  decision: RouteDecision,
  messages: ChatMessage[],
  opts: { apiKey?: string; withTools?: boolean; timeoutMs?: number } = {},
): Promise<Completion> {
  if (decision.status !== 'ok') throw new Error(`cannot call provider: ${decision.error_code}`);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), opts.timeoutMs ?? 120_000);
  try {
    if (decision.kind === 'ollama-native') {
      const res = await fetch(`${decision.endpoint}/api/chat`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ model: decision.model, messages, stream: false }),
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(`ollama ${res.status}: ${(await res.text()).slice(0, 200)}`);
      const body = (await res.json()) as { message?: { content?: string } };
      return { content: body.message?.content ?? '', tool_calls: [], raw: body };
    }
    const body: Record<string, unknown> = { model: decision.model, messages };
    if (opts.withTools) body.tools = TOOL_SCHEMA;
    const res = await fetch(`${decision.endpoint}/chat/completions`, {
      method: 'POST',
      headers: authHeaders(decision, opts.apiKey),
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`${decision.provider} ${res.status}: ${(await res.text()).slice(0, 300)}`);
    const payload = (await res.json()) as {
      choices?: Array<{ message?: { content?: string; tool_calls?: Array<{ id?: string; function: { name: string; arguments: string } }> } }>;
    };
    const message = payload.choices?.[0]?.message ?? {};
    const toolCalls: ToolCall[] = (message.tool_calls ?? []).map((c) => ({
      id: c.id ?? `call_${Math.random().toString(36).slice(2)}`,
      name: c.function.name,
      args: safeJson(c.function.arguments) as Record<string, unknown>,
    }));
    return { content: message.content ?? '', tool_calls: toolCalls, raw: payload };
  } finally {
    clearTimeout(timer);
  }
}

function safeJson(text: string): unknown {
  try { return JSON.parse(text); } catch { return { _raw: text }; }
}

/** Live loop: real model, real tools, real gate. Bounded by maxTurns. */
export async function runLiveLoop(
  decision: RouteDecision,
  prompt: string,
  ctx: ToolContext & { apiKey?: string },
  maxTurns = 6,
): Promise<LoopOutcome & { transcript: ChatMessage[] }> {
  const transcript: ChatMessage[] = [
    { role: 'system', content: 'You are zen-agent. Prefer calling a tool over guessing. Answer tersely.' },
    { role: 'user', content: prompt },
  ];
  const tools: string[] = [];
  const results: string[] = [];

  for (let turn = 0; turn < maxTurns; turn++) {
    const completion = await complete(decision, transcript, { apiKey: ctx.apiKey, withTools: true });
    if (completion.tool_calls.length === 0) {
      return { tools, results, final: completion.content.trim(), transcript };
    }
    transcript.push({
      role: 'assistant',
      content: completion.content ?? '',
      tool_calls: completion.tool_calls.map((call) => ({
        id: call.id,
        type: 'function' as const,
        function: { name: call.name, arguments: JSON.stringify(call.args) },
      })),
    });
    for (const call of completion.tool_calls) {
      const r = await runTool(call.name, call.args, ctx);
      tools.push(call.name);
      results.push(r.result);
      transcript.push({ role: 'tool', tool_call_id: call.id, name: call.name, content: r.result });
    }
  }
  return { tools, results, final: '', transcript };
}
