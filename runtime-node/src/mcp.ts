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
