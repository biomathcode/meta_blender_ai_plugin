---
name: blender-mcp-workflow
description: How this agent connects to Blender — Blender MCP socket (port 9876) health checks, structured tools vs execute_python, export timeouts. Use for MCP, connection, or "do anything in Blender" requests.
---

# Blender MCP Workflow

## Connection model
- This agent runs **inside Blender** (same `bpy` API the Blender MCP server exposes), so tool calls execute in-process on Blender's main thread — no socket round-trip, no deadlock with the MCP server's own main-thread executor.
- If the **Blender MCP** addon (github.com/ahujasid/blender-mcp) is also installed and serving on `127.0.0.1:9876`, the panel shows it as detected. External clients (Claude/Codex via MCP) can drive the same Blender through that socket; this agent's `execute_blender_python` is the in-process equivalent of MCP `execute_code`.
- Health check order (mirrors Blender MCP practice): `get_scene_info` → trivial `execute_blender_python("print('ok')")` → only then real work.

## Tool selection
- Prefer **structured tools** (`get_scene_info`, `create_primitive`, `add_modifier`, `optimize_scene`, …) — they are validated and return compact results.
- Use `execute_blender_python` only for what structured tools don't cover (custom node groups, bmesh edits, drivers, baking). Keep code short, print a summary, and verify with `get_scene_info`/`get_object_info` afterwards.
- Long exports: MCP servers time out on GLTF export. This agent exports in-process with `export_glb` (apply=False, no Draco) — same settings, no timeout.

## Safety inside the loop
- One tool call = one verifiable change. Re-inspect after destructive steps (delete, decimate-apply, purge).
- Report what changed (names, counts, sizes), never just "done".
