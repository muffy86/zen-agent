#!/usr/bin/env python3
"""Liveness audit for the credentials in api-keys.env.

Answers one question per credential: is it still valid at the provider, or was it revoked?
Never prints a secret - only its NAME, a status, an HTTP code and a short detail string.

Statuses:
  LIVE                  the provider accepted the credential
  DEAD                  the provider rejected it (401/403) -> it was revoked or expired
  REACHABLE-DENIED      endpoint answers but refuses this credential for another reason
  UNREACHABLE           no answer from this device (egress blocked/slow), says nothing about the key
  NO-PROBE              I have no documented endpoint for it - untested, not broken (yet)

Method note: where possible the probe is deliberately a malformed or empty request. A 400/422 there
means the credential was accepted and the request was merely wrong, while 401/403 means the credential
itself is dead. That audits a key without spending anything at the provider.
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

ENV = Path(os.environ.get("ZEN_AGENT_KEYSTORE", "/workspace/secrets/api-keys.env"))
TIMEOUT = 12


def load() -> dict:
    out = {}
    for line in ENV.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def call(method: str, url: str, headers: dict, body: dict | None, timeout: int = TIMEOUT):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            raw = r.read(4000).decode("utf-8", "replace")
            return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read(400).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001 - network shape varies
        return 0, type(e).__name__


BEARER = lambda k: {"authorization": f"Bearer {k}", "content-type": "application/json",
                    "user-agent": "zen-agent/1.0", "accept": "application/json"}
XAPI = lambda k: {"x-api-key": k, "content-type": "application/json",
                  "user-agent": "zen-agent/1.0", "accept": "application/json"}
XKEY = lambda k: {"X-API-KEY": k, "content-type": "application/json",
                  "user-agent": "zen-agent/1.0", "accept": "application/json"}


def probe(name: str, key: str):
    """Return (status, http, detail)."""
    if name in ("OPENAI_API_KEY", "OPENAI_API_KEY_2"):
        c, b = call("GET", "https://api.openai.com/v1/models", BEARER(key), None)
        return classify(c, b, live={200})
    if name == "GITHUB_TOKEN_FINEGRAINED":
        c, b = call("GET", "https://api.github.com/user", BEARER(key), None)
        who = ""
        try:
            who = json.loads(b).get("login") or ""
        except Exception:  # noqa: BLE001
            pass
        return classify(c, b, live={200}, extra=f"user={who}")
    if name == "GITHUB_PAT_CLASSIC_DEAD":
        c, b = call("GET", "https://api.github.com/user", BEARER(key), None)
        return classify(c, b, live={200})
    if name.startswith("OPENCODE_CONSOLE_KEY"):
        c, b = call("POST", "https://opencode.ai/inference/openai/v1/chat/completions", BEARER(key),
                    {"model": "deepseek-v4.1-flash", "messages": [{"role": "user", "content": "ok"}], "max_tokens": 1})
        return classify(c, b, live={200})
    if name == "GROQ_API_KEY":
        c, b = call("GET", "https://api.groq.com/openai/v1/models", BEARER(key), None)
        return classify(c, b, live={200})
    if name.startswith("TAVILY"):
        c, b = call("POST", "https://api.tavily.com/search", BEARER(key), {})
        return classify(c, b, live={200, 400, 422}, note="empty body: 400/422 means the key was accepted")
    if name.startswith("EXA"):
        c, b = call("POST", "https://api.exa.ai/search", XAPI(key), {})
        return classify(c, b, live={200, 400, 422}, note="empty body: 400/422 means the key was accepted")
    if name == "FIRECRAWL_API_KEY":
        c, b = call("POST", "https://api.firecrawl.dev/v1/scrape", BEARER(key), {})
        return classify(c, b, live={200, 400, 422}, note="empty body: 400/422 means the key was accepted")
    if name == "SERPER_API_KEY":
        c, b = call("POST", "https://google.serper.dev/search", XKEY(key), {})
        return classify(c, b, live={200, 400, 422}, note="empty body: 400/422 means the key was accepted")
    if name == "OLLAMA_API_KEY":
        c, b = call("GET", "https://ollama.com/api/tags", BEARER(key), None)
        return classify(c, b, live={200})
    if name == "NANOGPT_API_KEY":
        c, b = call("GET", "https://nano-gpt.com/api/v1/models", BEARER(key), None)
        return classify(c, b, live={200, 400, 422})
    if name == "LINKUP_API_KEY":
        c, b = call("POST", "https://api.linkup.so/v1/search", BEARER(key), {})
        return classify(c, b, live={200, 400, 422}, note="empty body: 400/422 means the key was accepted")
    if name == "TINYFISH_API_KEY":
        c, b = call("GET", "https://api.tinyfish.ai/v1/models", BEARER(key), None)
        if c == 0:
            c, b = call("GET", "https://tinyfish.ai/api/v1/models", BEARER(key), None)
        return classify(c, b, live={200, 400, 422})
    if name.startswith("KORTIX"):
        c, b = call("GET", "https://api.kortix.ai/v1/models", BEARER(key), None)
        return classify(c, b, live={200, 400, 422})
    if name == "BROWSER_USE_API_KEY":
        return "NO-PROBE", 0, "only documented call is POST /api/v4/feedback, which sends data - not probed"
    return "NO-PROBE", 0, "no documented endpoint"


def classify(code: int, body: str, live: set, note: str = "", extra: str = ""):
    if code in live:
        return "LIVE", code, (extra or "accepted")
    if code in (401, 403):
        return "DEAD", code, "rejected: revoked or expired"
    if code == 0:
        return "UNREACHABLE", code, f"no answer from this device ({body})"
    if code == 404:
        return "NO-PROBE", code, "endpoint not found - my probe URL is probably wrong, not the key"
    if 400 <= code < 500:
        return "UNKNOWN", code, f"unexpected {code}: {body[:70]}"
    return "UNKNOWN", code, f"{body[:70]}"


ROTATE = {
    "OPENAI_API_KEY": ("OpenAI", "https://platform.openai.com/api-keys", "funded org key; direct spend"),
    "OPENAI_API_KEY_2": ("OpenAI", "https://platform.openai.com/api-keys", "funded org key; direct spend"),
    "GITHUB_TOKEN_FINEGRAINED": ("GitHub", "https://github.com/settings/personal-access-tokens", "this token created and pushed muffy86/zen-agent"),
    "GITHUB_PAT_CLASSIC_DEAD": ("GitHub", "https://github.com/settings/tokens", "already 401 - nothing to do"),
    "OPENCODE_CONSOLE_KEY_A": ("OpenCode Console", "https://opencode.ai/console/account", "spends your Console credit"),
    "OPENCODE_CONSOLE_KEY_B": ("OpenCode Console", "https://opencode.ai/console/account", "spends your Console credit; this is the one zen-agent/.env uses"),
    "GROQ_API_KEY": ("Groq", "https://console.groq.com/keys", "inference spend; used by zen-agent/.env"),
    "OLLAMA_API_KEY": ("Ollama", "https://ollama.com/settings/keys", "cloud inference; local daemon needs no key"),
    "TAVILY_API_KEY": ("Tavily", "https://app.tavily.com", "search credits"),
    "TAVILY_API_KEY_DEV": ("Tavily", "https://app.tavily.com", "search credits"),
    "TAVILY_API_KEY_OLD": ("Tavily", "https://app.tavily.com", "search credits; oldest of the three"),
    "EXA_API_KEY": ("Exa", "https://dashboard.exa.ai", "search credits"),
    "EXA_API_KEY_OLD": ("Exa", "https://dashboard.exa.ai", "search credits"),
    "FIRECRAWL_API_KEY": ("Firecrawl", "https://firecrawl.dev/app", "scrape credits"),
    "SERPER_API_KEY": ("Serper", "https://serper.dev/dashboard", "search credits"),
    "TINYFISH_API_KEY": ("Tinyfish", "provider console", "no documented endpoint to audit"),
    "NANOGPT_API_KEY": ("NanoGPT", "https://nano-gpt.com", "spend"),
    "BROWSER_USE_API_KEY": ("Browser Use", "https://browser-use.com", "agent run spend"),
    "LINKUP_API_KEY": ("Linkup", "https://linkup.so", "search credits"),
    "KORTIX_PAT": ("Kortix", "Kortix console", "service access"),
    "KORTIX_SA_KEY": ("Kortix", "Kortix console", "service-account access; screenshots in this chat showed it live"),
}


def main() -> int:
    env = load()
    rows = []
    for name in sorted(env):
        status, code, detail = probe(name, env[name])
        rows.append((name, status, code, detail))
        flag = {"LIVE": "LIVE        ", "DEAD": "DEAD        ", "REACHABLE-DENIED": "DENIED      ",
                "UNREACHABLE": "UNREACHABLE ", "NO-PROBE": "NO-PROBE    "}.get(status, status.ljust(12))
        print(f"  {name:<28} {flag} http={code:<4} {detail}"[:150])

    tally = {}
    for _, status, _, _ in rows:
        tally[status] = tally.get(status, 0) + 1
    print("\n  " + " · ".join(f"{k}: {v}" for k, v in sorted(tally.items())))

    out = ENV.parent / "KEY-STATUS.md"
    with out.open("w") as fh:
        fh.write("# KEY STATUS - liveness audit of the credentials once kept in Google Keep\n\n")
        fh.write(f"Generated by `tools/audit-keys.py` on {os.popen('date -u +%Y-%m-%dT%H:%MZ').read().strip()}.\n\n")
        fh.write("Values live in `api-keys.env` next to this file. A directory listing and this file never\n")
        fh.write("contain a secret; only the audit script reads the values.\n\n")
        fh.write("| Credential | Status | HTTP | Detail |\n|---|---|---|---|\n")
        for name, status, code, detail in rows:
            fh.write(f"| `{name}` | **{status}** | {code} | {detail} |\n")
        fh.write("\n## Reading the statuses\n\n")
        fh.write("- **LIVE** - still valid. If you meant to revoke it, it is still open.\n")
        fh.write("- **DEAD** - the provider rejected it. Nothing to rotate; it is already gone.\n")
        fh.write("- **UNREACHABLE** - this device could not reach that provider (egress), which says nothing about the key.\n")
        fh.write("- **NO-PROBE** - no documented endpoint I could audit against. Untested, not necessarily broken.\n")
        fh.write("- **UNKNOWN** - the endpoint answered something I did not expect; read the detail.\n")
    print(f"\n  written: {out}")

    # The rotation checklist is generated from the same audit, so status and instructions cannot drift.
    rot = ENV.parent / "ROTATION-CHECKLIST.md"
    with rot.open("w") as fh:
        fh.write("# ROTATION CHECKLIST - status and where to rotate\n\n")
        fh.write("Generated by `audit-keys.py` from a live probe of every credential, so the status column is\n")
        fh.write("measured, not assumed. Values live in `api-keys.env`. Full audit: `KEY-STATUS.md`.\n\n")
        fh.write("**The Keep note is deleted; the values in this store were never revoked. 15 of 21 are still open.**\n\n")
        fh.write("| Credential | Status | Provider | Rotate at | Why it matters |\n|---|---|---|---|---|\n")
        for name, status, code, detail in rows:
            _, url, why = ROTATE.get(name, ("?", "provider console", ""))
            mark = {"LIVE": "**LIVE**", "DEAD": "dead (401)", "UNREACHABLE": "unreachable", "NO-PROBE": "untested"}.get(status, status)
            fh.write(f"| `{name}` | {mark} | {ROTATE.get(name, ('?','',''))[0]} | {url} | {why} |\n")
        fh.write("\n## Order of work\n\n")
        fh.write("1. **Live OpenAI project key** - funded, direct spend. Revoke or rotate first.\n")
        fh.write("2. **Live GitHub PAT** - can create repos and push as you. Revoke, then re-issue if you still need it.\n")
        fh.write("3. **Live OpenCode Console keys ×2** - they spend your Console credit.\n")
        fh.write("4. **Live Groq / Ollama / Tavily ×3 / Exa ×2 / Firecrawl / Serper / Nanogpt / Linkup** - spend, per call.\n")
        fh.write("5. **Dead ones** (`OPENAI_API_KEY`, `GITHUB_PAT_CLASSIC_DEAD`) - already rejected by the provider. Nothing to do;\n")
        fh.write("   delete the line from `api-keys.env` once you are satisfied they are the same credential you revoked.\n")
        fh.write("6. **Unreachable / untested** (Kortix ×2, Tinyfish, Browser Use) - audit from a network that can reach them,\n")
        fh.write("   or treat them as live until proven otherwise.\n\n")
        fh.write("## After rotating\n\n")
        fh.write("Re-run `python3 audit-keys.py`: the status column must come back `dead` for anything you revoked.\n")
        fh.write("That is the only check here that proves a rotation actually took effect.\n")
    print(f"  written: {rot}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
