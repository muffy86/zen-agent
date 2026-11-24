// zen-agent — minimal MCP stdio client. Enough to list and call tools on any MCP server.
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';

interface JsonRpcResponse { id?: number; result?: unknown; error?: { code: number; message: string } }

export class McpStdioClient {
  private child?: ChildProcessWithoutNullStreams;
  private buffer = '';
  private nextId = 1;
  private pending = new Map<number, (r: JsonRpcResponse) => void>();

  constructor(private readonly command: string, private readonly args: string[] = [], private readonly env: Record<string, string> = {}) {}

  async start(timeoutMs = 15_000): Promise<void> {
    this.child = spawn(this.command, this.args, { env: { ...process.env, ...this.env }, stdio: ['pipe', 'pipe', 'pipe'] });
    this.child.stdout.setEncoding('utf8');
    this.child.stdout.on('data', (chunk: string) => this.onData(chunk));
    await this.request('initialize', {
      protocolVersion: '2025-06-18',
      capabilities: {},
      clientInfo: { name: 'zen-agent', version: '1.0.0' },
    }, timeoutMs);
    this.notify('notifications/initialized', {});
  }

  private onData(chunk: string): void {
    this.buffer += chunk;
    let index = this.buffer.indexOf('\n');
    while (index >= 0) {
      const line = this.buffer.slice(0, index).trim();
      this.buffer = this.buffer.slice(index + 1);
      if (line !== '') {
        try {
          const msg = JSON.parse(line) as JsonRpcResponse;
          if (typeof msg.id === 'number' && this.pending.has(msg.id)) {
            this.pending.get(msg.id)!(msg);
            this.pending.delete(msg.id);
          }
        } catch { /* MCP servers may log non-JSON lines: ignore, keep the stream alive */ }
      }
      index = this.buffer.indexOf('\n');
    }
  }

  private send(payload: Record<string, unknown>): void {
    this.child?.stdin.write(`${JSON.stringify(payload)}\n`);
  }

  private notify(method: string, params: unknown): void {
    this.send({ jsonrpc: '2.0', method, params });
  }

  private request(method: string, params: unknown, timeoutMs = 30_000): Promise<JsonRpcResponse> {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`mcp timeout: ${method}`)); }, timeoutMs);
      this.pending.set(id, (r) => { clearTimeout(timer); resolve(r); });
      this.send({ jsonrpc: '2.0', id, method, params });
    });
  }

  async listTools(): Promise<Array<{ name: string; description?: string }>> {
    const r = await this.request('tools/list', {});
    const result = r.result as { tools?: Array<{ name: string; description?: string }> } | undefined;
    return result?.tools ?? [];
  }

  async callTool(name: string, args: Record<string, unknown>): Promise<unknown> {
    const r = await this.request('tools/call', { name, arguments: args });
    if (r.error) throw new Error(`mcp tool error: ${r.error.message}`);
    return r.result;
  }

  close(): void {
    this.child?.kill();
  }
}

/**
 * HTTP MCP transport (streamable HTTP with SSE replies).
 *
 * The device's own gateway exposes MCP over HTTP — e.g. http://127.0.0.1:8801/mcp/ (browser control)
 * and http://127.0.0.1:8802/mcp (Android control) — so a stdio-only client could not reach the most
 * useful tools on this machine. Both transports expose the same two calls the agent needs.
 */
export class McpHttpClient {
  private nextId = 1;
  /**
   * The gateway hands out a session id on `initialize` and rejects later calls with
   * "Bad Request: Missing session ID" unless it is echoed back (MCP streamable-HTTP transport).
   */
  private sessionId?: string;

  constructor(private readonly url: string, private readonly headers: Record<string, string> = {}) {}

  private static extract(text: string, id: number): JsonRpcResponse | null {
    for (const line of text.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed.startsWith('data:')) continue;
      try {
        const message = JSON.parse(trimmed.slice(5).trim()) as JsonRpcResponse;
        if (message.id === id) return message;
      } catch { /* non-JSON keepalive line */ }
    }
    try {
      const message = JSON.parse(text) as JsonRpcResponse;
      return message.id === id ? message : null;
    } catch {
      return null;
    }
  }

  private async rpc(method: string, params: unknown, timeoutMs = 30_000): Promise<JsonRpcResponse | null> {
    const id = this.nextId++;
    const response = await fetch(this.url, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        accept: 'application/json, text/event-stream',
        ...(this.sessionId ? { 'mcp-session-id': this.sessionId } : {}),
        ...this.headers,
      },
      body: JSON.stringify({ jsonrpc: '2.0', id, method, params }),
      signal: AbortSignal.timeout(timeoutMs),
    });
    const issued = response.headers.get('mcp-session-id');
    if (issued) this.sessionId = issued;
    const text = await response.text();
    if (!response.ok) throw new Error(`mcp http ${response.status}: ${text.slice(0, 200)}${this.sessionId ? ' (session id was sent)' : ''}`);
    return McpHttpClient.extract(text, id);
  }

  async start(): Promise<void> {
    this.sessionId = undefined; // always begin a fresh session
    const init = await this.rpc('initialize', {
      protocolVersion: '2025-06-18',
      capabilities: {},
      clientInfo: { name: 'zen-agent', version: '1.0.0' },
    });
    if (!init?.result) throw new Error(`mcp http initialize failed: ${JSON.stringify(init?.error ?? {})}`);
    await this.rpc('notifications/initialized', {}).catch(() => null); // notifications may return 202/empty
  }

  async listTools(): Promise<Array<{ name: string; description?: string }>> {
    const response = await this.rpc('tools/list', {});
    return (response?.result as { tools?: Array<{ name: string; description?: string }> } | undefined)?.tools ?? [];
  }

  async callTool(name: string, args: Record<string, unknown>): Promise<unknown> {
    const response = await this.rpc('tools/call', { name, arguments: args });
    if (response?.error) throw new Error(`mcp tool error: ${response.error.message}`);
    return response?.result;
  }

  close(): void { /* stateless HTTP: nothing to release */ }
}
