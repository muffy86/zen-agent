#!/usr/bin/env python3
"""Cross-language differential test.

The point of a polyglot runtime is that the heads agree. This script drives the *same* routing
requests through the TypeScript, Python and Kotlin heads as separate processes and compares the
decisions field by field, including the human-readable `reason`. Nothing here is mocked: these are
three real binaries.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "protocol" / "fixtures"
KOTLIN_JAR = ROOT / "core-kotlin" / "build" / "libs" / "zen-agent-kotlin-core-1.0.0-all.jar"
VIEW_FIELDS = [
    "status", "route_id", "capability", "provider", "model", "tier",
    "auth_style", "key_required", "fallback_providers", "error_code",
]

HEADS = {
    "node": ["node", str(ROOT / "runtime-node" / "dist" / "cli.js"), "route"],
    "python": [str(ROOT / "tools-python" / ".venv" / "bin" / "python"), "-m", "zen_agent.cli", "route"],
    "kotlin": ["java", "-jar", str(KOTLIN_JAR), "route"],
}


def flags(request: dict) -> list[str]:
    out: list[str] = []
    if request.get("capability"):
        out += ["--capability", request["capability"]]
    if request.get("prompt"):
        out += ["--prompt", request["prompt"]]
    if request.get("tags"):
        out += ["--tags", ",".join(request["tags"])]
    if request.get("prefer"):
        out += ["--prefer", request["prefer"]]
    if request.get("providers_available"):
        out += ["--available", ",".join(request["providers_available"])]
    if request.get("providers_down"):
        out += ["--down", ",".join(request["providers_down"])]
    if request.get("env_keys"):
        out += ["--env", ",".join(request["env_keys"])]
    if request.get("free_only"):
        out += ["--free-only"]
    return out + ["--json"]


def project(decision: dict) -> dict:
    """Pick the asserted fields out of a raw decision. `fallbacks` carries {provider, model} objects;
    the vectors assert the provider ids, so the projection flattens them here, once."""
    view = {field: decision.get(field) for field in VIEW_FIELDS}
    if view["fallback_providers"] is None:
        view["fallback_providers"] = [item["provider"] for item in decision.get("fallbacks") or []]
    return view


def invoke(head: str, request: dict) -> dict:
    command = HEADS[head] + flags(request)
    proc = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    if proc.returncode not in (0, 3):  # 3 = a deliberate routing error, still a valid answer
        raise RuntimeError(f"{head} exited {proc.returncode}: {proc.stderr.strip()[:300]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{head} produced non-JSON output: {proc.stdout[:200]!r}") from exc


def main() -> int:
    required = {
        "node": ROOT / "runtime-node" / "dist" / "cli.js",
        "python": ROOT / "tools-python" / ".venv" / "bin" / "python",
        "kotlin": KOTLIN_JAR,
    }
    absent = [name for name, path in required.items() if not path.exists()]
    if absent:
        print(f"cannot run: missing build products for {', '.join(absent)} — run ./build.sh first")
        return 2

    cases = json.loads((FIXTURES / "routing-cases.json").read_text(encoding="utf-8"))["cases"]
    checks = failures = 0
    print(f"differential routing: {len(cases)} requests x {len(HEADS)} heads")
    for case in cases:
        request = case["request"]
        try:
            decisions = {head: invoke(head, request) for head in HEADS}
        except RuntimeError as exc:
            print(f"  ERROR {case['id']}: {exc}")
            failures += 1
            checks += 1
            continue
        views = {head: project(decision) for head, decision in decisions.items()}
        reference_head = "node"
        reference = views[reference_head]
        problems = []
        for head, view in views.items():
            if view != reference:
                for field in VIEW_FIELDS:
                    if view[field] != reference[field]:
                        problems.append(f"{head}.{field}: {view[field]!r} != {reference[field]!r}")
        # the free-text reason must agree too: three implementations, one sentence
        reasons = {head: decisions[head].get("reason") for head in HEADS}
        if len(set(reasons.values())) != 1:
            problems.append(f"reason differs: {reasons}")
        # and all three must satisfy the golden vector itself
        want = case["expect"]
        for field, expected in want.items():
            if reference.get(field) != expected:
                problems.append(f"node.{field}: {reference.get(field)!r} != fixture {expected!r}")
        checks += 1
        if problems:
            failures += 1
            print(f"  FAIL {case['id']}: " + "; ".join(problems))
        else:
            print(f"  PASS {case['id']}: {reference['route_id'] or reference['error_code']} (3 heads identical)")
    print(f"\ndifferential (3 heads): {checks - failures}/{checks} requests agree")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
