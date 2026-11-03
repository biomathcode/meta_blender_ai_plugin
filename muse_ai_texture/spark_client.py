"""Meta Muse Spark chat client with tool calling (bpy-free).

Uses the OpenAI-compatible Chat Completions endpoint on the Meta Model API:
  POST https://api.meta.ai/v1/chat/completions
  {"model": "muse-spark-1.3", "messages": [...], "tools": [...]}
Assistant replies may carry `tool_calls[].function.{name, arguments}`.
Verified live against muse-spark-1.3 (plain chat + forced tool call).
"""

from __future__ import annotations

import json

try:  # package import (inside Blender)
    from .api_client import DEFAULT_BASE_URL, MuseAPIError, _request_json
except ImportError:  # standalone load (tests)
    import importlib.util
    import os
    import sys
    _spec = importlib.util.spec_from_file_location(
        "muse_api_client", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "api_client.py"))
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["muse_api_client"] = _mod
    _spec.loader.exec_module(_mod)
    DEFAULT_BASE_URL = _mod.DEFAULT_BASE_URL
    MuseAPIError = _mod.MuseAPIError
    _request_json = _mod._request_json

DEFAULT_SPARK_MODEL = "muse-spark-1.3"
SPARK_MODELS = ("muse-spark-1.3", "muse-spark-1.2", "muse-spark-1.1")


def chat_completion(messages, tools, api_key, model=DEFAULT_SPARK_MODEL,
                    base_url=DEFAULT_BASE_URL, timeout=300):
    """One chat turn. Returns the assistant message dict (content/tool_calls)."""
    if not api_key:
        raise MuseAPIError("No Meta API key (META_API_KEY in .env or Preferences).")
    payload = {"model": model or DEFAULT_SPARK_MODEL, "messages": messages}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    data = _request_json(f"{base_url.rstrip('/')}/chat/completions",
                         api_key, payload=payload, timeout=timeout)
    choices = data.get("choices") or []
    if not choices:
        raise MuseAPIError(f"No choices in Spark response: {json.dumps(data)[:300]}")
    message = choices[0].get("message") or {}
    # Normalise tool_calls arguments to parsed dicts for the agent loop.
    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                fn["arguments_parsed"] = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError:
                fn["arguments_parsed"] = {}
    return message
