"""Blender MCP bridge (socket protocol of github.com/ahujasid/blender-mcp).

The Blender MCP addon serves JSON commands on 127.0.0.1:9876, e.g.
{"type": "execute_code", "params": {"code": "..."}} ->
{"status": "success", "result": {...}}.

This agent normally runs *inside* Blender, where tool calls already execute
on Blender's main thread through the same bpy API — routing them through the
socket from the main thread would deadlock against the MCP server's own
main-thread executor. So:

* `probe()` detects a running MCP server (safe from any thread),
* `execute_code()` uses the socket when Blender is NOT available in this
  process (external agent scripts) and falls back to in-process exec inside
  Blender. Both paths are the same execution Blender MCP would perform.
"""

from __future__ import annotations

import io
import json
import socket
from contextlib import redirect_stdout

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9876


def probe(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
          timeout: float = 0.6) -> bool:
    """True when something accepts TCP connections on the MCP address."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _send_command(command_type: str, params: dict, host: str, port: int,
                  timeout: float = 30.0) -> dict:
    payload = json.dumps({"type": command_type, "params": params}).encode()
    buffer = b""
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(payload)
        sock.settimeout(timeout)
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buffer += chunk
            try:
                return json.loads(buffer.decode())
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
    raise ConnectionError("Blender MCP server closed without a JSON reply.")


def execute_code(code: str, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 prefer_mcp: bool = False, timeout: float = 30.0) -> tuple[bool, str]:
    """Run Python in Blender. Returns (ok, output). See module docstring."""
    try:
        import bpy  # noqa: F401
        in_blender = True
    except ImportError:
        in_blender = False

    if prefer_mcp or not in_blender:
        if probe(host, port):
            try:
                reply = _send_command("execute_code", {"code": code},
                                      host, port, timeout=timeout)
                result = reply.get("result", reply)
                text = result.get("result", "") if isinstance(result, dict) else str(result)
                return reply.get("status") == "success", str(text)[:4000]
            except (OSError, ConnectionError, ValueError) as exc:
                if in_blender:
                    pass  # fall through to in-process execution
                else:
                    return False, f"Blender MCP error: {exc}"
        elif not in_blender:
            return False, ("Blender MCP server not reachable on "
                           f"{host}:{port} and bpy is unavailable here.")

    # In-process execution (inside Blender) — captures print() output.
    import bpy

    stream = io.StringIO()
    namespace = {"bpy": bpy}
    try:
        with redirect_stdout(stream):
            exec(compile(code, "<muse-agent>", "exec"), namespace)  # noqa: S102
        return True, stream.getvalue()[:4000] or "(executed, no output)"
    except Exception as exc:  # noqa: BLE001 - reported to the agent/user
        return False, f"{type(exc).__name__}: {exc}\n{stream.getvalue()[:1000]}"
