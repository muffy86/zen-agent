"""zen-agent — provider registry + deterministic routing (protocol §2, §3)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

TIER_RANK = {"local": 0, "free": 1, "paid": 2}

# Capability inference: first match wins; the order is part of the protocol.
CAPABILITY_TABLE = [
    ("voice", re.compile(r"\b(?:voice|speak|audio|tts|transcribe)\b")),
    ("vision", re.compile(r"\b(?:image|screenshot|photo|vision|ocr)\b")),
    ("math", re.compile(r"\b(?:math|calcul\w*|arithmetic|integral|equation|solve)\b")),
    ("long", re.compile(r"\b(?:summar\w*|digest|document|pdf|translat\w*|long-context)\b")),
    ("code", re.compile(r"\b(?:code|refactor|debug|compile|typescript|kotlin|python|java|script|api|endpoint)\b")),
    ("reason", re.compile(r"\b(?:reason\w*|plan|analy\w*|strategy|proof|why)\b")),
]

REPO_ROOT = Path(__file__).resolve().parents[2]


def repo_root() -> Path:
    import os

    return Path(os.environ.get("ZEN_AGENT_ROOT") or REPO_ROOT)


def infer_capability(request: Dict[str, Any]) -> str:
    if request.get("capability"):
        return str(request["capability"])
    tags = request.get("tags") or []
    hay = " ".join([*tags, request.get("prompt") or ""]).lower()
    for capability, pattern in CAPABILITY_TABLE:
        if pattern.search(hay):
            return capability
    return "chat"


def load_registry(path: Optional[Path] = None) -> Dict[str, Any]:
    target = Path(path) if path else repo_root() / "providers" / "providers.json"
    registry = json.loads(target.read_text(encoding="utf-8"))
    if not registry.get("providers"):
        raise ValueError(f"registry {target} has no providers")
    return registry


def eligible(provider: Dict[str, Any], request: Dict[str, Any], capability: str) -> bool:
    available = request.get("providers_available")
    if available is not None and provider["id"] not in available:
        return False
    if provider["id"] in (request.get("providers_down") or []):
        return False
    if capability not in provider.get("models", {}):
        return False
    auth = provider.get("auth", {})
    if auth.get("key_required") and auth.get("key_env") not in (request.get("env_keys") or []):
        return False
    if request.get("free_only") and auth.get("key_required"):
        return False
    return True


def _sort_key(prefer: str, provider: Dict[str, Any]):
    tier = TIER_RANK.get(provider.get("tier", ""), 3)
    if prefer == "local":
        return (0 if provider.get("tier") == "local" else 1, provider["priority"], provider["id"])
    if prefer == "quality":
        return (provider["priority"], tier, provider["id"])
    return (tier, provider["priority"], provider["id"])


def _error(capability: str, prefer: str) -> Dict[str, Any]:
    return {
        "status": "error",
        "route_id": None,
        "capability": capability,
        "provider": None,
        "model": None,
        "endpoint": None,
        "kind": None,
        "tier": None,
        "auth_style": None,
        "auth_key_env": None,
        "key_required": None,
        "prefer": prefer,
        "fallbacks": [],
        "reason": "no candidate survived the filter set",
        "error_code": "no_provider_for_capability",
        "error": {
            "code": "no_provider_for_capability",
            "message": f"no provider can serve capability '{capability}'",
        },
    }


def route(registry: Dict[str, Any], request: Dict[str, Any]) -> Dict[str, Any]:
    capability = infer_capability(request)
    prefer = request.get("prefer") or "balanced"
    candidates = [p for p in registry["providers"] if eligible(p, request, capability)]
    if not candidates:
        return _error(capability, prefer)

    ordered = sorted(candidates, key=lambda p: _sort_key(prefer, p))
    chosen = ordered[0]
    fallbacks = [
        {"provider": p["id"], "model": p["models"][capability]} for p in ordered[1:4]
    ]
    auth = chosen["auth"]
    key_required = bool(auth.get("key_required"))
    return {
        "status": "ok",
        "route_id": f"rt-{capability}-{chosen['id']}",
        "capability": capability,
        "provider": chosen["id"],
        "model": chosen["models"][capability],
        "endpoint": chosen["base_url"],
        "kind": chosen["kind"],
        "tier": chosen["tier"],
        "auth_style": auth.get("style") if key_required else "none",
        "auth_key_env": auth.get("key_env") if key_required else None,
        "key_required": key_required,
        "prefer": prefer,
        "fallbacks": fallbacks,
        "reason": (
            f"tier={chosen['tier']} priority={chosen['priority']} "
            f"candidates={len(candidates)} prefer={prefer}"
        ),
        "error_code": None,
    }


def assertable_view(decision: Dict[str, Any]) -> Dict[str, Any]:
    """The exact projection every runtime must agree on."""
    return {
        "status": decision.get("status"),
        "route_id": decision.get("route_id"),
        "capability": decision.get("capability"),
        "provider": decision.get("provider"),
        "model": decision.get("model"),
        "tier": decision.get("tier"),
        "auth_style": decision.get("auth_style"),
        "key_required": decision.get("key_required"),
        "fallback_providers": [f["provider"] for f in decision.get("fallbacks") or []],
        "error_code": decision.get("error_code"),
    }
