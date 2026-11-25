"""zen-agent — CLI + golden-vector conformance harness (protocol §8.3)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

from .agent import run_live_loop, run_scripted_loop
from .policy import evaluate, load_rules
from .router import assertable_view, load_registry, repo_root, route
from .tools import run_tool

__version__ = "1.0.0"


def _fixtures() -> Path:
    return repo_root() / "protocol" / "fixtures"


def load_dotenv() -> None:
    """Load .env from the repo root and the cwd. Real environment always wins: this never overrides."""
    import os

    for path in (repo_root() / ".env", Path.cwd() / ".env"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip().removeprefix("export").strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def present_env_keys() -> List[str]:
    """Which of the registry's credentials does this machine actually hold?"""
    return [key for key in
            (provider["auth"].get("key_env") for provider in load_registry()["providers"])
            if key and os.environ.get(key)]


def with_local_credentials(request: Dict[str, Any]) -> Dict[str, Any]:
    """A real CLI routes with the credentials present here; an explicit --env list always wins."""
    if request.get("env_keys"):
        return request
    request = dict(request)
    request["env_keys"] = present_env_keys()
    return request


def conformance() -> int:
    registry = load_registry()
    rules = load_rules()
    checks = failures = 0

    def report(suite: str, case_id: str, problems: List[str]) -> None:
        nonlocal checks, failures
        checks += 1
        if problems:
            failures += 1
            print(f"  FAIL {suite}/{case_id}: {'; '.join(problems)}")
        else:
            print(f"  PASS {suite}/{case_id}")

    print(f"routing ({len(registry['providers'])} providers in registry)")
    routing = json.loads((_fixtures() / "routing-cases.json").read_text(encoding="utf-8"))
    for case in routing["cases"]:
        view = assertable_view(route(registry, case["request"]))
        problems = [
            f"{key}: want {json.dumps(want)} got {json.dumps(view.get(key))}"
            for key, want in case["expect"].items()
            if view.get(key) != want
        ]
        report("routing", case["id"], problems)

    print("policy")
    policy = json.loads((_fixtures() / "policy-cases.json").read_text(encoding="utf-8"))
    for case in policy["cases"]:
        verdict = evaluate(policy["rules"], case["tool"], case["args"])
        problems = []
        if verdict["decision"] != case["expect"]["decision"]:
            problems.append(f"decision: want {case['expect']['decision']} got {verdict['decision']}")
        if verdict["code"] != case["expect"]["code"]:
            problems.append(f"code: want {case['expect']['code']} got {verdict['code']}")
        report("policy", case["id"], problems)

    print("tool loop")
    tool_cases = json.loads((_fixtures() / "tool-cases.json").read_text(encoding="utf-8"))
    ctx = {"root": repo_root(), "rules": policy["rules"], "live": False}
    for case in tool_cases["cases"]:
        got = run_scripted_loop(case["script"], ctx)
        expect = case["expect"]
        problems = []
        if got["tools"] != expect["tools"]:
            problems.append(f"tools: want {expect['tools']} got {got['tools']}")
        if got["results"] != expect["results"]:
            problems.append(f"results: want {expect['results']} got {got['results']}")
        if got["final"] != expect["final"]:
            problems.append(f"final: want {expect['final']!r} got {got['final']!r}")
        report("tools", case["id"], problems)

    print(f"\nconformance (python): {checks - failures}/{checks} vectors pass")
    return failures


def doctor() -> int:
    registry = load_registry()
    reachable = 0
    for provider in registry["providers"]:
        url = f"{provider['base_url']}/api/tags" if provider["kind"] == "ollama-native" else f"{provider['base_url']}/models"
        try:
            with urllib.request.urlopen(url, timeout=4) as response:  # noqa: S310
                status = str(response.status)
                if response.status == 200:
                    reachable += 1
        except Exception as exc:
            status = f"error:{type(exc).__name__}"
        print(f"{provider['id']:<16} {provider['tier']:<6} {status:<12} {url}")
    print(f"\nreachable: {reachable}/{len(registry['providers'])}")
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zen-agent-py", description="polyglot agentic runtime (python head)")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("providers")
    sub.add_parser("env")
    route_parser = sub.add_parser("route")
    route_parser.add_argument("--capability")
    route_parser.add_argument("--prompt")
    route_parser.add_argument("--tags")
    route_parser.add_argument("--prefer", default="balanced")
    route_parser.add_argument("--available")
    route_parser.add_argument("--down")
    route_parser.add_argument("--env")
    route_parser.add_argument("--free-only", action="store_true")
    route_parser.add_argument("--json", action="store_true")

    infer_parser = sub.add_parser("infer")
    infer_parser.add_argument("--prompt", default="")
    infer_parser.add_argument("--tags", default="")

    tool_parser = sub.add_parser("tool")
    tool_parser.add_argument("name")
    tool_parser.add_argument("--args", default="{}")
    tool_parser.add_argument("--live", action="store_true")

    loop_parser = sub.add_parser("loop")
    loop_parser.add_argument("--script", required=True)

    live_parser = sub.add_parser("live")
    live_parser.add_argument("--capability", default="chat")
    live_parser.add_argument("--prompt", default="reply with exactly: ZEN_OK")
    live_parser.add_argument("--prefer", default="local")
    live_parser.add_argument("--available")
    live_parser.add_argument("--down")
    live_parser.add_argument("--env")
    live_parser.add_argument("--free-only", action="store_true")

    memory_parser = sub.add_parser("memory")
    memory_parser.add_argument("--query", default="")

    mcp_parser = sub.add_parser("mcp")
    mcp_parser.add_argument("target", help="http(s) MCP url, or a command for stdio")
    mcp_parser.add_argument("--call")
    mcp_parser.add_argument("--args", default="{}")

    sub.add_parser("conformance")
    sub.add_parser("doctor")
    sub.add_parser("selftest")
    args = parser.parse_args(argv)
    load_dotenv()

    from .router import infer_capability

    if args.command == "env":
        registry = load_registry()
        env_file = repo_root() / ".env"
        print(f"env file: {env_file if env_file.exists() else 'none - copy .env.example to .env'}")
        present = 0
        for provider in registry["providers"]:
            key = provider["auth"].get("key_env")
            if not key:
                print(f"  - {provider['id']:<16} (no credential needed)")
                continue
            have = bool(os.environ.get(key))
            present += 1 if have else 0
            print(f"{'*' if have else 'o'} {provider['id']:<16} {key}")
        print(f"\n{present} credential(s) present. The local tier needs none.")
        return 0

    if args.command == "providers":
        registry = load_registry()
        for provider in registry["providers"]:
            mark = "●" if provider["verified"]["reachable"] else "○"
            print(f"{mark} {provider['id']:<16} {provider['tier']:<6} {provider['priority']:>3} {provider['kind']:<18} {provider['base_url']}")
        return 0

    if args.command == "route":
        request: Dict[str, Any] = {
            "capability": args.capability,
            "prompt": args.prompt,
            "tags": args.tags.split(",") if args.tags else None,
            "prefer": args.prefer,
            "providers_available": args.available.split(",") if args.available else None,
            "providers_down": args.down.split(",") if args.down else None,
            "env_keys": args.env.split(",") if args.env else [],
            "free_only": args.free_only,
        }
        request = {k: v for k, v in request.items() if v is not None}
        decision = route(load_registry(), with_local_credentials(request))
        if args.json:
            print(json.dumps(decision, indent=2))
        else:
            fallbacks = ", ".join(f["provider"] for f in decision["fallbacks"]) or "none"
            print(f"{decision['status']} {decision.get('route_id') or decision['error_code']} -> "
                  f"{decision['provider'] or '-'} / {decision['model'] or '-'} (fallbacks: {fallbacks})")
        return 0 if decision["status"] == "ok" else 3

    if args.command == "infer":
        tags = args.tags.split(",") if args.tags else []
        print(infer_capability({"prompt": args.prompt, "tags": tags}))
        return 0

    if args.command == "tool":
        ctx = {"root": repo_root(), "rules": load_rules(), "live": args.live}
        print(json.dumps(run_tool(args.name, json.loads(args.args), ctx), indent=2))
        return 0

    if args.command == "loop":
        ctx = {"root": repo_root(), "rules": load_rules(), "live": False}
        print(json.dumps(run_scripted_loop(json.loads(args.script), ctx), indent=2))
        return 0

    if args.command == "live":
        from .memory import MemoryStore

        live_request: Dict[str, Any] = {"capability": args.capability, "prefer": args.prefer}
        if args.available:
            live_request["providers_available"] = args.available.split(",")
        if args.down:
            live_request["providers_down"] = args.down.split(",")
        if args.env:
            live_request["env_keys"] = args.env.split(",")
        if args.free_only:
            live_request["free_only"] = True
        decision = route(load_registry(), with_local_credentials(live_request))
        api_key = os.environ.get(decision["auth_key_env"] or "", None)
        outcome = run_live_loop(decision, args.prompt, {"root": repo_root(), "rules": load_rules(), "live": True}, api_key)
        MemoryStore(repo_root() / "memory" / "memory.jsonl").append(
            {"kind": "answer", "route": decision["route_id"], "tools": outcome["tools"], "final": outcome["final"]}
        )
        print(json.dumps({"route": decision["route_id"], "provider": decision["provider"], "model": decision["model"],
                          "tools": outcome["tools"], "results": outcome["results"], "final": outcome["final"]}, indent=2))
        return 0

    if args.command == "memory":
        from .memory import MemoryStore

        print(json.dumps(MemoryStore(repo_root() / "memory" / "memory.jsonl").recall(args.query), indent=2))
        return 0

    if args.command == "mcp":
        from .mcp_client import McpHttpClient, McpStdioClient

        client = McpHttpClient(args.target) if args.target.startswith("http") else McpStdioClient(args.target)
        client.start()
        if args.call:
            print(json.dumps(client.call_tool(args.call, json.loads(args.args)), indent=2))
        else:
            tools = client.list_tools()
            for tool in tools:
                print(f"{tool['name']:<28} {(tool.get('description') or '')[:90]}")
            print(f"\n{len(tools)} tools from {args.target}")
        client.close()
        return 0

    if args.command == "conformance":
        return 1 if conformance() else 0

    if args.command == "doctor":
        return doctor()

    if args.command == "selftest":
        registry = load_registry()
        decision = route(registry, {"capability": "code", "prefer": "local"})
        print(f"registry: {len(registry['providers'])} providers")
        print(f"route:    {decision['route_id']} -> {decision['model']} @ {decision['endpoint']}")
        print(f"python:   {sys.version.split()[0]}")
        print(f"root:     {repo_root()}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
