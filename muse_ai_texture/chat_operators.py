"""Chat operators: the async agentic loop + chat utilities.

The loop alternates: Spark HTTP call on a worker thread -> tool execution
on Blender's main thread (modal TIMER) -> next Spark call, until Spark
answers without tool calls, the step limit hits, or the user stops it.
"""

from __future__ import annotations

import threading
import time

import bpy
from bpy.props import StringProperty

from . import agent_loop, agent_tools, mcp_bridge, spark_client, utils

_STATE: dict = {"thread": None, "result": None, "error": "", "messages": [],
                "iteration": 0, "timer_started": False}


def _llm_worker(messages, tools, api_key, model, base_url):
    try:
        _STATE["result"] = spark_client.chat_completion(
            messages, tools, api_key, model=model, base_url=base_url)
        _STATE["error"] = ""
    except Exception as exc:  # noqa: BLE001 - shown in chat
        _STATE["result"] = None
        _STATE["error"] = str(exc)


class MUSE_OT_chat_send(bpy.types.Operator):
    bl_idname = "muse.chat_send"
    bl_label = "Send to Agent"
    bl_description = "Send the message to the Muse Spark Blender agent"
    bl_options = {"REGISTER"}

    _timer = None

    def invoke(self, context, event):
        agent = context.scene.muse_agent
        if agent.is_running:
            self.report({"WARNING"}, "Agent is already working. Stop it first.")
            return {"CANCELLED"}
        text = agent.input_text.strip()
        if not text:
            self.report({"WARNING"}, "Type a message first.")
            return {"CANCELLED"}
        key, _source, _url, _model = utils.api_settings(context)
        if not key:
            agent.status = "No Meta API key (META_API_KEY in .env or Preferences)."
            self.report({"ERROR"}, agent.status)
            return {"CANCELLED"}

        agent_loop.append_chat(context, "user", text)
        agent.input_text = ""
        _STATE.update(messages=agent_loop.build_messages(context, text)[:-1],
                      iteration=0, result=None, error="", thread=None)
        agent.is_running = True
        agent.stop_requested = False
        agent.status = f"Agent starting ({agent_loop.effective_model(agent)})…"
        self._start_llm(context)
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.3, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _start_llm(self, context):
        agent = context.scene.muse_agent
        key, _source, base_url, _model = utils.api_settings(context)
        _STATE["iteration"] += 1
        agent.status = (f"Thinking… (step {_STATE['iteration']}/"
                        f"{agent.max_iterations}, {agent_loop.effective_model(agent)})")
        thread = threading.Thread(
            target=_llm_worker,
            args=(list(_STATE["messages"]), agent_tools.tool_schemas(),
                  key, agent_loop.effective_model(agent), base_url),
            daemon=True)
        _STATE["thread"] = thread
        thread.start()

    def modal(self, context, event):
        agent = context.scene.muse_agent
        if event.type in {"ESC"} or agent.stop_requested:
            return self._finish(context, "Stopped by user.")
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        thread = _STATE.get("thread")
        if thread is not None and thread.is_alive():
            return {"PASS_THROUGH"}

        if _STATE.get("error"):
            return self._finish(context, f"Error: {_STATE['error']}", error=True)
        message = _STATE.get("result")
        if message is None:
            return {"PASS_THROUGH"}

        calls = message.get("tool_calls") or []
        _STATE["messages"].append(
            {"role": "assistant", "content": message.get("content") or "",
             **({"tool_calls": calls} if calls else {})})
        if not calls:
            final = (message.get("content") or "").strip() or "(no reply)"
            agent_loop.append_chat(context, "assistant", final)
            return self._finish(context, "Ready.")
        if _STATE["iteration"] >= agent.max_iterations:
            agent_loop.append_chat(context, "assistant",
                                   f"Stopped after {agent.max_iterations} steps (limit). "
                                   "Ask me to continue if needed.")
            return self._finish(context, "Step limit reached.")

        for call in calls:  # main thread: safe bpy tool execution
            fn = call.get("function") or {}
            name = fn.get("name", "")
            args = fn.get("arguments_parsed") or {}
            agent.status = f"Running tool {name}…"
            result = agent_tools.execute_tool(context, name, args)
            agent_loop.append_chat(context, "tool", f"{name} -> {result}")
            _STATE["messages"].append({"role": "tool",
                                       "tool_call_id": call.get("id", name),
                                       "content": result})
        _STATE["result"] = None
        self._start_llm(context)
        return {"PASS_THROUGH"}

    def _finish(self, context, status, error=False):
        agent = context.scene.muse_agent
        agent.is_running = False
        agent.stop_requested = False
        agent.status = status
        if error:
            agent_loop.append_chat(context, "assistant", status)
            self.report({"ERROR"}, status)
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        return {"FINISHED"} if not error else {"CANCELLED"}


class MUSE_OT_chat_stop(bpy.types.Operator):
    bl_idname = "muse.chat_stop"
    bl_label = "Stop Agent"

    def execute(self, context):
        context.scene.muse_agent.stop_requested = True
        context.scene.muse_agent.status = "Stopping after the current step…"
        return {"FINISHED"}


class MUSE_OT_chat_clear(bpy.types.Operator):
    bl_idname = "muse.chat_clear"
    bl_label = "Clear Chat"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        context.scene.muse_chat.clear()
        context.scene.muse_agent.chat_index = -1
        context.scene.muse_agent.status = "Chat cleared. Ask me to build, texture, optimize…"
        return {"FINISHED"}


class MUSE_OT_chat_quick(bpy.types.Operator):
    bl_idname = "muse.chat_quick"
    bl_label = "Quick Prompt"
    bl_description = "Fill the chat input with a ready-made request"

    prompt: StringProperty(default="", options={"HIDDEN"})
    task: StringProperty(default="", options={"HIDDEN"})

    def execute(self, context):
        agent = context.scene.muse_agent
        if self.task in ("BLENDER", "SITE", "CUSTOM"):
            agent.task_type = self.task
        agent.input_text = self.prompt
        return {"FINISHED"}


class MUSE_OT_mcp_health(bpy.types.Operator):
    bl_idname = "muse.mcp_health"
    bl_label = "Check Blender MCP"
    bl_description = "Probe the Blender MCP server on 127.0.0.1:9876"

    def invoke(self, context, event):
        agent = context.scene.muse_agent
        agent.mcp_status = "Blender MCP: checking…"

        def worker():
            found = mcp_bridge.probe()
            _STATE["mcp_result"] = found

        _STATE["mcp_result"] = None
        threading.Thread(target=worker, daemon=True).start()

        def check():
            if _STATE.get("mcp_result") is None:
                return 0.3
            found = _STATE["mcp_result"]
            agent.mcp_status = (
                f"Blender MCP: DETECTED on {mcp_bridge.DEFAULT_HOST}:{mcp_bridge.DEFAULT_PORT} "
                "(external MCP clients can drive this Blender; this agent runs "
                "in-process on the same bpy API)."
                if found else
                f"Blender MCP: not running on {mcp_bridge.DEFAULT_HOST}:{mcp_bridge.DEFAULT_PORT}. "
                "Agent still works in-process; install the Blender MCP addon "
                "only if external tools need the socket.")
            return None

        bpy.app.timers.register(check, first_interval=0.4)
        return {"FINISHED"}


classes = (MUSE_OT_chat_send, MUSE_OT_chat_stop, MUSE_OT_chat_clear,
           MUSE_OT_chat_quick, MUSE_OT_mcp_health)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
