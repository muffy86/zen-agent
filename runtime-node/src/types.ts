// zen-agent — shared types (protocol v1)
export type Capability =
  | 'chat' | 'code' | 'reason' | 'vision' | 'long' | 'math' | 'voice' | 'free' | 'embed';

export interface ProviderAuth {
  style: string;
  key_required: boolean;
  key_env: string | null;
  key_env_extra?: string | null;
}

export interface Provider {
  id: string;
  label: string;
  kind: string;
  base_url: string;
  auth: ProviderAuth;
  tier: 'local' | 'free' | 'paid' | string;
  priority: number;
  verified?: { reachable: boolean; checked: string | null; evidence: string };
  models: Record<string, string>;
}

export interface Registry {
  version: number;
  generated: string;
  providers: Provider[];
}

export type Prefer = 'balanced' | 'local' | 'quality';

export interface RouteRequest {
  capability?: string;
  tags?: string[];
  prompt?: string;
  prefer?: Prefer;
  providers_available?: string[];
  providers_down?: string[];
  env_keys?: string[];
  free_only?: boolean;
}

export interface Fallback { provider: string; model: string }

export interface RouteDecision {
  status: 'ok' | 'error';
  route_id?: string;
  capability: string;
  provider: string | null;
  model?: string | null;
  endpoint?: string | null;
  kind?: string | null;
  tier?: string | null;
  auth_style?: string | null;
  auth_key_env?: string | null;
  key_required?: boolean | null;
  prefer?: Prefer;
  fallbacks: Fallback[];
  reason?: string;
  error_code: string | null;
  error?: { code: string; message: string };
}

export interface PolicyRules {
  enabled_tools: string[];
  write_roots: string[];
  network_allow: string[];
  max_calc_ops: number;
  deny_arg_patterns: string[];
}

export interface Verdict { decision: 'allow' | 'deny'; code: string }

export interface ToolResult {
  tool: string;
  ok: boolean;
  result: string;
  decision: 'allow' | 'deny';
  code: string;
}

export interface ScriptTurn {
  tool_call?: { name: string; args: Record<string, unknown> };
  final?: string;
}

export interface LoopOutcome { tools: string[]; results: string[]; final: string }

export interface ToolContext {
  root: string;
  rules: PolicyRules;
  /** false = golden-vector mode: nothing touches the network or a live provider */
  live: boolean;
}
