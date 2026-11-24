"""zen-agent — minimal MCP stdio client (JSON-RPC, newline-delimited). List and call tools."""
from __future__ import annotations

import json
import subprocess
import threading
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
