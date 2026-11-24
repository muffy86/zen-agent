"""zen-agent — the agent loop (protocol §7): scripted (golden vectors) and live (real provider)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .tools import TOOL_SCHEMA, run_tool


def run_scripted_loop(script: List[Dict[str, Any]], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic loop over a scripted transcript. The gate and tools are real; only the model is a script."""
    tools: List[str] = []
    results: List[str] = []
    final = ""
    for turn in script:
        if "tool_call" in turn:
            call = turn["tool_call"]
            outcome = run_tool(call["name"], call.get("args") or {}, ctx)
            tools.append(call["name"])
            results.append(outcome["result"])
            continue
        if "final" in turn:
            final = str(turn["final"])
            break
    return {"tools": tools, "results": results, "final": final}


def _headers(decision: Dict[str, Any], api_key: Optional[str]) -> Dict[str, str]:
    headers = {"content-type": "application/json"}
    if api_key:
        if decision.get("auth_style") == "bearer":
            headers["authorization"] = f"Bearer {api_key}"
        elif decision.get("auth_style") == "x-api-key":
            headers["x-api-key"] = api_key
        elif decision.get("auth_style") == "api-key":
            headers["api-key"] = api_key
    return headers


def complete(
    decision: Dict[str, Any],
    messages: List[Dict[str, str]],
    api_key: Optional[str] = None,
    with_tools: bool = False,
    timeout: int = 120,
) -> Dict[str, Any]:
    """One model turn against the routed provider. Ollama speaks its native shape; everything else OpenAI."""
    if decision.get("status") != "ok":
        raise RuntimeError(f"cannot call provider: {decision.get('error_code')}")
    endpoint = decision["endpoint"]
    if decision.get("kind") == "ollama-native":
        payload = {"model": decision["model"], "messages": messages, "stream": False}
        request = urllib.request.Request(
            f"{endpoint}/api/chat", data=json.dumps(payload).encode(), headers={"content-type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (routed endpoint)
            body = json.loads(response.read().decode())
        return {"content": (body.get("message") or {}).get("content", ""), "tool_calls": [], "raw": body}

    payload: Dict[str, Any] = {"model": decision["model"], "messages": messages}
    if with_tools:
        payload["tools"] = TOOL_SCHEMA
    request = urllib.request.Request(
        f"{endpoint}/chat/completions",
        data=json.dumps(payload).encode(),
        headers=_headers(decision, api_key),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{decision['provider']} {exc.code}: {exc.read()[:300]!r}") from exc

    message = ((body.get("choices") or [{}])[0] or {}).get("message") or {}
    tool_calls = []
    for call in message.get("tool_calls") or []:
        raw_args = call["function"].get("arguments") or "{}"
        try:
            parsed = json.loads(raw_args)
        except json.JSONDecodeError:
            parsed = {"_raw": raw_args}
        tool_calls.append({
            "id": call.get("id") or f"call_{len(tool_calls)}",
            "name": call["function"]["name"],
            "args": parsed,
            "raw_arguments": raw_args,
        })
    return {"content": message.get("content") or "", "tool_calls": tool_calls, "raw": body}


def run_live_loop(
    decision: Dict[str, Any],
    prompt: str,
    ctx: Dict[str, Any],
    api_key: Optional[str] = None,
    max_turns: int = 6,
) -> Dict[str, Any]:
    """Live loop: real model, real tools, real gate. Bounded by max_turns."""
    transcript: List[Dict[str, str]] = [
        {"role": "system", "content": "You are zen-agent. Prefer calling a tool over guessing. Answer tersely."},
        {"role": "user", "content": prompt},
    ]
    tools: List[str] = []
    results: List[str] = []
    for _ in range(max_turns):
        completion = complete(decision, transcript, api_key=api_key, with_tools=True)
        if not completion["tool_calls"]:
            return {"tools": tools, "results": results, "final": completion["content"].strip(), "transcript": transcript}
        # the assistant turn must carry the calls, and each tool result must carry its id:
        # OpenAI-compatible gateways reject a tool message without a non-empty tool_call_id
        transcript.append({
            "role": "assistant",
            "content": completion["content"],
            "tool_calls": [
                {"id": call["id"], "type": "function",
                 "function": {"name": call["name"], "arguments": json.dumps(call["args"])}}
                for call in completion["tool_calls"]
            ],
        })
        for call in completion["tool_calls"]:
            outcome = run_tool(call["name"], call["args"], ctx)
            tools.append(call["name"])
            results.append(outcome["result"])
            transcript.append({"role": "tool", "tool_call_id": call["id"], "name": call["name"], "content": outcome["result"]})
    return {"tools": tools, "results": results, "final": "", "transcript": transcript}
