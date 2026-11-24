"""zen-agent — the policy gate (protocol §5). Runs BEFORE any tool, in every mode."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def load_rules(path: Path | None = None) -> Dict[str, Any]:
    from .router import repo_root

    target = Path(path) if path else repo_root() / "protocol" / "fixtures" / "policy-cases.json"
    doc = json.loads(target.read_text(encoding="utf-8"))
    if "rules" not in doc:
        raise ValueError(f"policy fixture {target} has no 'rules' block")
    return doc["rules"]


def check_write_path(raw: str, roots: list) -> Tuple[str, str, Optional[str]]:
    """(decision, code, normalised_path). Absolute paths and escapes are refused."""
    if raw.startswith("/"):
        return "deny", "path_outside_write_root", None
    out: list = []
    for seg in raw.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            # popping past the first segment means the caller tried to leave the sandbox
            if len(out) <= 1:
                return "deny", "path_traversal", None
            out.pop()
            continue
        out.append(seg)
    if not out or out[0] not in roots:
        return "deny", "path_outside_write_root", None
    return "allow", "ok", "/".join(out)


def normalize_rel(raw: str) -> str:
    """Pure normalisation of a relative read path (no root confinement, only traversal safety)."""
    out: list = []
    for seg in raw.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if out:
                out.pop()
            continue
        out.append(seg)
    return "/".join(out)


def evaluate(rules: Dict[str, Any], tool: str, args: Dict[str, Any]) -> Dict[str, str]:
    # 1. only tools on the list exist at all — shell.exec is absent on purpose
    if tool not in rules["enabled_tools"]:
        return {"decision": "deny", "code": "tool_not_enabled"}

    # 2. prompt-injection hygiene: arguments are data, never instructions
    haystack = json.dumps(args or {}).lower()
    for pattern in rules["deny_arg_patterns"]:
        if pattern.lower() in haystack:
            return {"decision": "deny", "code": "injection_suspected"}

    # 3. filesystem writes stay inside a root, with no traversal
    if tool == "fs.write":
        decision, code, _ = check_write_path(str((args or {}).get("path", "")), rules["write_roots"])
        if decision == "deny":
            return {"decision": decision, "code": code}

    # reads are not confined to write roots, but must not climb out of the project
    if tool == "fs.read":
        raw = str((args or {}).get("path", ""))
        if raw.startswith("/"):
            return {"decision": "deny", "code": "path_outside_write_root"}
        depth = 0
        for seg in raw.split("/"):
            if seg in ("", "."):
                continue
            if seg == "..":
                if depth == 0:
                    return {"decision": "deny", "code": "path_traversal"}
                depth -= 1
                continue
            depth += 1

    # 4. network egress is an allow-list of origins
    if tool == "net.get":
        url = str((args or {}).get("url", ""))
        if not any(url.startswith(origin) for origin in rules["network_allow"]):
            return {"decision": "deny", "code": "host_not_allowed"}

    # 5. cheap guard against unbounded work
    if tool == "calc":
        if len(str((args or {}).get("expression", ""))) > rules["max_calc_ops"]:
            return {"decision": "deny", "code": "expression_too_large"}

    return {"decision": "allow", "code": "ok"}
