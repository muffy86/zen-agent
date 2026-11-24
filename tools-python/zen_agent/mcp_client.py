"""zen-agent — minimal MCP stdio client (JSON-RPC, newline-delimited). List and call tools."""
from __future__ import annotations

import json
import subprocess
import threading
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


class McpStdioClient:
    def __init__(self, command: str, args: Optional[List[str]] = None, env: Optional[Dict[str, str]] = None) -> None:
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.proc: Optional[subprocess.Popen] = None
        self._next_id = 1
        self._pending: Dict[int, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._event = threading.Event()

    def start(self) -> None:
        import os

        env = {**os.environ, **self.env}
        self.proc = subprocess.Popen(  # noqa: S603 (caller-supplied command, same trust level as a shell)
            [self.command, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=env,
        )
        threading.Thread(target=self._reader, daemon=True).start()
        self.request(
            "initialize",
            {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "zen-agent", "version": "1.0.0"}},
        )
        self.notify("notifications/initialized", {})

    def _reader(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue  # servers may log non-JSON: keep the stream alive
            with self._lock:
                waiter = self._pending.pop(message.get("id"), None)
                if waiter is not None:
                    waiter["response"] = message
                    waiter["event"].set()

    def _send(self, payload: Dict[str, Any]) -> None:
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def notify(self, method: str, params: Any) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: Any, timeout: float = 30.0) -> Dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        waiter: Dict[str, Any] = {"event": threading.Event(), "response": None}
        with self._lock:
            self._pending[request_id] = waiter
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        if not waiter["event"].wait(timeout):
            with self._lock:
                self._pending.pop(request_id, None)
            raise TimeoutError(f"mcp timeout: {method}")
        return waiter["response"]

    def list_tools(self) -> List[Dict[str, Any]]:
        return (self.request("tools/list", {}).get("result") or {}).get("tools") or []

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        response = self.request("tools/call", {"name": name, "arguments": arguments})
        if "error" in response:
            raise RuntimeError(f"mcp tool error: {response['error'].get('message')}")
        return response.get("result")

    def close(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


class McpHttpClient:
    """HTTP MCP transport (streamable HTTP with SSE replies).

    The device's own gateway exposes MCP over HTTP — http://127.0.0.1:8801/mcp/ (browser control)
    and http://127.0.0.1:8802/mcp (Android control) — so a stdio-only client cannot reach the most
    useful tools on this machine. The gateway answers `initialize` with an `mcp-session-id` header and
    then rejects later calls with "Bad Request: Missing session ID" unless it is echoed back.
    """

    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None) -> None:
        self.url = url
        self.headers = headers or {}
        self.session_id: Optional[str] = None
        self._next_id = 1

    @staticmethod
    def _extract(text: str, request_id: int) -> Optional[Dict[str, Any]]:
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            try:
                message = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue  # keepalive or non-JSON line
            if message.get("id") == request_id:
                return message
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            return None
        return message if message.get("id") == request_id else None

    def _rpc(self, method: str, params: Any, timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        request_id = self._next_id
        self._next_id += 1
        headers = {"content-type": "application/json", "accept": "application/json, text/event-stream"}
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        headers.update(self.headers)
        request = urllib.request.Request(
            self.url,
            data=json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (caller-supplied url)
                issued = response.headers.get("mcp-session-id")
                if issued:
                    self.session_id = issued
                text = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:200]
            raise RuntimeError(f"mcp http {exc.code}: {body}") from exc
        return self._extract(text, request_id)

    def start(self) -> None:
        self.session_id = None  # always begin a fresh session
        init = self._rpc("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "zen-agent", "version": "1.0.0"},
        })
        if not init or "result" not in init:
            raise RuntimeError(f"mcp http initialize failed: {init}")
        try:
            self._rpc("notifications/initialized", {})  # notifications may answer 202 with no body
        except Exception:  # noqa: BLE001 - a notification failure is not fatal
            pass

    def list_tools(self) -> List[Dict[str, Any]]:
        response = self._rpc("tools/list", {}) or {}
        return (response.get("result") or {}).get("tools") or []

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        response = self._rpc("tools/call", {"name": name, "arguments": arguments}) or {}
        if "error" in response:
            raise RuntimeError(f"mcp tool error: {response['error'].get('message')}")
        return response.get("result")

    def close(self) -> None:
        return None  # stateless HTTP: nothing to release
