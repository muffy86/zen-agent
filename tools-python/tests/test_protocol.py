"""The same golden vectors the TypeScript and Kotlin heads are held to, as pytest assertions."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from zen_agent import (
    MemoryStore,
    calc,
    evaluate,
    infer_capability,
    load_registry,
    load_rules,
    route,
    run_scripted_loop,
)
from zen_agent.router import assertable_view

ROOT = Path(os.environ.get("ZEN_AGENT_ROOT", Path(__file__).resolve().parents[2]))
FIXTURES = ROOT / "protocol" / "fixtures"
REGISTRY = load_registry()
RULES = load_rules()
ROUTING = json.loads((FIXTURES / "routing-cases.json").read_text(encoding="utf-8"))["cases"]
POLICY = json.loads((FIXTURES / "policy-cases.json").read_text(encoding="utf-8"))["cases"]
TOOLS = json.loads((FIXTURES / "tool-cases.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", ROUTING, ids=[c["id"] for c in ROUTING])
def test_routing_vectors(case):
    view = assertable_view(route(REGISTRY, case["request"]))
    for key, want in case["expect"].items():
        assert view[key] == want, f"{case['id']} {key}: want {want!r} got {view[key]!r}"


@pytest.mark.parametrize("case", POLICY, ids=[c["id"] for c in POLICY])
def test_policy_vectors(case):
    verdict = evaluate(RULES, case["tool"], case["args"])
    assert verdict["decision"] == case["expect"]["decision"], case["id"]
    assert verdict["code"] == case["expect"]["code"], case["id"]


@pytest.mark.parametrize("case", TOOLS, ids=[c["id"] for c in TOOLS])
def test_tool_loop_vectors(case):
    got = run_scripted_loop(case["script"], {"root": ROOT, "rules": RULES, "live": False})
    assert got["tools"] == case["expect"]["tools"], case["id"]
    assert got["results"] == case["expect"]["results"], case["id"]
    assert got["final"] == case["expect"]["final"], case["id"]


def test_calculator_truncates_toward_zero():
    assert calc("6*7") == 42
    assert calc("(2+3)*4") == 20
    assert calc("-5 + (10/3)") == -2  # not -3: truncation, not flooring
    with pytest.raises(Exception, match="division_by_zero"):
        calc("1/0")


def test_capability_inference_order():
    assert infer_capability({"prompt": "transcribe this audio"}) == "voice"
    assert infer_capability({"prompt": "read this screenshot"}) == "vision"
    assert infer_capability({"tags": ["solve the integral"]}) == "math"
    assert infer_capability({"prompt": "summarize the pdf"}) == "long"
    assert infer_capability({"tags": ["refactor kotlin"]}) == "code"
    assert infer_capability({"prompt": "plan the strategy"}) == "reason"
    assert infer_capability({"prompt": "hello there"}) == "chat"


def test_unknown_provider_is_an_error_not_a_guess():
    decision = route(REGISTRY, {"capability": "chat", "providers_available": ["does-not-exist"]})
    assert decision["status"] == "error"
    assert decision["error_code"] == "no_provider_for_capability"


def test_memory_roundtrip(tmp_path):
    store = MemoryStore(tmp_path / "memory.jsonl")
    store.append({"kind": "answer", "route": "rt-code-clawrouter", "final": "ZEN_OK"})
    store.append({"kind": "note", "text": "unrelated"})
    assert store.read()[-1]["kind"] == "note"
    assert store.recall("clawrouter")[0]["route"] == "rt-code-clawrouter"


@pytest.mark.skipif(os.environ.get("ZEN_AGENT_LIVE") != "1", reason="needs a live provider (set ZEN_AGENT_LIVE=1)")
def test_live_completion():
    from zen_agent import complete

    decision = route(REGISTRY, {"capability": "chat", "prefer": "local"})
    completion = complete(decision, [{"role": "user", "content": "reply with exactly: ZEN_OK"}])
    assert "ZEN_OK" in completion["content"]
