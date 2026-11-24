"""zen-agent — tools (protocol §6): every call goes through the gate first."""
from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Any, Dict

from .policy import check_write_path, evaluate, normalize_rel


class CalcError(ValueError):
    pass


def _trunc_div(a: int, b: int) -> int:
    """Integer division that truncates toward zero (Python's // floors negatives)."""
    if b == 0:
        raise CalcError("division_by_zero")
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


def calc(expression: str) -> int:
    """Integer arithmetic: + - * / and parentheses. Division truncates toward zero."""
    src = "".join(expression.split())
    pos = 0

    def peek() -> str | None:
        return src[pos] if pos < len(src) else None

    def expr() -> int:
        nonlocal pos
        value = term()
        while peek() in ("+", "-"):
            op = src[pos]
            pos += 1
            rhs = term()
            value = value + rhs if op == "+" else value - rhs
        return value

    def term() -> int:
        nonlocal pos
        value = factor()
        while peek() in ("*", "/"):
            op = src[pos]
            pos += 1
            rhs = factor()
            value = value * rhs if op == "*" else _trunc_div(value, rhs)
        return value

    def factor() -> int:
        nonlocal pos
        ch = peek()
        if ch == "-":
            pos += 1
            return -factor()
        if ch == "(":
            pos += 1
            value = expr()
            if peek() != ")":
                raise CalcError("unbalanced_parenthesis")
            pos += 1
            return value
        start = pos
        while peek() is not None and src[pos].isdigit():
            pos += 1
        if pos == start:
            raise CalcError(f"not_a_number_at_{start}")
        return int(src[start:pos])

    value = expr()
    if pos != len(src):
        raise CalcError(f"trailing_input_at_{pos}")
    return value


def run_tool(name: str, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    args = args or {}
    verdict = evaluate(ctx["rules"], name, args)
    if verdict["decision"] == "deny":
        return {"tool": name, "ok": False, "result": f"DENIED:{verdict['code']}", "decision": "deny", "code": verdict["code"]}

    try:
        if name == "calc":
            return _ok(name, str(calc(str(args.get("expression", "")))), verdict["code"])
        if name == "fs.read":
            rel = normalize_rel(str(args.get("path", "")))
            body = (Path(ctx["root"]) / rel).read_text(encoding="utf-8").rstrip()
            return _ok(name, body, verdict["code"])
        if name == "fs.write":
            _, code, rel = check_write_path(str(args.get("path", "")), ctx["rules"]["write_roots"])
            full = Path(ctx["root"]) / (rel or "")
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(str(args.get("content", "")), encoding="utf-8")
            return _ok(name, f"ok:{rel}", verdict["code"])
        if name == "text.echo":
            return _ok(name, str(args.get("text", "")), verdict["code"])
        if name == "net.get":
            url = str(args.get("url", ""))
            if not ctx.get("live"):
                return _ok(name, "STUB:no-network-in-fixture-mode", verdict["code"])
            with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 (allow-listed)
                body = response.read(256).decode("utf-8", "replace")
            return _ok(name, f"{response.status} {body}", verdict["code"])
        return {"tool": name, "ok": False, "result": f"ERROR:unknown_tool:{name}", "decision": "allow", "code": "unknown_tool"}
    except Exception as exc:  # tool errors are data, never crashes
        return {"tool": name, "ok": False, "result": f"ERROR:{exc}", "decision": "allow", "code": "tool_error"}


def _ok(tool: str, result: str, code: str) -> Dict[str, Any]:
    return {"tool": tool, "ok": True, "result": result, "decision": "allow", "code": code}


TOOL_SCHEMA = [
    {"type": "function", "function": {"name": "calc", "description": "Integer arithmetic: + - * / and parentheses.",
     "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}}},
    {"type": "function", "function": {"name": "fs.read", "description": "Read a file inside the sandbox root.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "fs.write", "description": "Write a file inside a configured write root.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
]
