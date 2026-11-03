"""Agentic loop: Muse Spark <-> Blender tools until the task is done.

One iteration = one Spark chat call (tool-calling) + executing every tool
call it requested on Blender's main thread. The synchronous runner below is
used by tests/scripts; the chat operator drives the same steps through a
modal timer so the UI stays responsive (LLM HTTP on a worker thread, tool
execution on the main thread).
"""

from __future__ import annotations

from . import agent_tools, skills, spark_client, utils

SYSTEM_PROMPT = """You are the Muse Blender Agent inside Blender. You control Blender \
through tools and must ACT, not just describe: create, edit, texture, light, \
animate, optimize and export by calling tools, then verify results.

Rules:
- Start by inspecting (get_scene_info / list_objects) when you don't know the scene.
- Prefer structured tools; use execute_blender_python only for what they cannot do, \
keep code short, print a summary, and re-inspect afterwards.
- For specialist work (optimization, baking, size reduction, materials, lighting, \
Three.js visual quality, diorama, export, animation, Geometry Nodes), call \
get_skill first and follow it.
- Product showcase order is fixed: optimize_for_web (Smart, not decimate-only) \
-> bake_product_maps -> create_showcase_animation -> seed_cms -> build_website \
-> check_site. Never render or export the GLB before baking.
- After destructive or heavy steps (delete, optimize, purge), verify counts.
- Never claim success a tool did not confirm. Report names, counts and sizes.
- Finish with a short Markdown summary (heading + bullets + a code block for \
any serve command). Keep lines short: the chat panel renders Markdown \
structure, and long unbroken paragraphs wrap badly. Do not call tools after finishing.

Available skills (get_skill by id):
{skills}
"""


MODEL_FOR_TASK = {"BLENDER": "muse-spark-1.1", "SITE": "muse-spark-1.3"}


def effective_model(settings) -> str:
    """Model tier for the chat task: lower for Blender work, higher for sites."""
    if getattr(settings, "task_type", "CUSTOM") == "CUSTOM":
        return settings.spark_model
    return MODEL_FOR_TASK.get(settings.task_type, settings.spark_model)


def build_messages(context, user_text: str) -> list[dict]:
    """System prompt (with auto-loaded skills) + recent chat + the request."""
    auto = skills.select_skills(user_text)
    skill_text = ""
    for skill_id in auto:
        skill_text += f"\n\n--- SKILL {skill_id} ---\n{skills.get_skill(skill_id)}"
    system = SYSTEM_PROMPT.format(skills=skills.list_skills_text()) + skill_text
    messages: list[dict] = [{"role": "system", "content": system}]
    for item in list(context.scene.muse_chat)[-10:]:
        if item.role in ("user", "assistant") and item.text:
            messages.append({"role": item.role, "content": item.text[:1500]})
    messages.append({"role": "user", "content": user_text})
    return messages


def append_chat(context, role: str, text: str) -> None:
    item = context.scene.muse_chat.add()
    item.role = role
    item.text = text[:4000]
    context.scene.muse_agent.chat_index = len(context.scene.muse_chat) - 1


def run_agent_sync(context, user_text: str, client_fn=None, max_iterations: int = 12) -> str:
    """Run the full loop synchronously (headless/scripts/tests).

    `client_fn(messages, tools) -> assistant message dict` is injectable so
    tests can drive the loop without network access.
    """
    settings = context.scene.muse_agent
    if client_fn is None:
        key, _source, base_url, _model = utils.api_settings(context)

        def client_fn(messages, tools):  # noqa: F811 - intentional default
            return spark_client.chat_completion(
                messages, tools, key, model=effective_model(settings),
                base_url=base_url)

    append_chat(context, "user", user_text)
    messages = build_messages(context, user_text)
    # build_messages already appended the current user turn via history; the
    # last history entry IS this turn, so drop the duplicate we would add.
    messages = messages[:-1] if messages and messages[-1].get("content") == user_text else messages

    tools = agent_tools.tool_schemas()
    final_text = ""
    for iteration in range(1, max_iterations + 1):
        settings.status = f"Thinking… (step {iteration}/{max_iterations}, {effective_model(settings)})"
        message = client_fn(messages, tools)
        messages.append({"role": "assistant",
                         "content": message.get("content") or "",
                         "tool_calls": message.get("tool_calls") or []} if message.get("tool_calls") else
                        {"role": "assistant", "content": message.get("content") or ""})
        calls = message.get("tool_calls") or []
        if not calls:
            final_text = (message.get("content") or "").strip() or "(no reply)"
            break
        for call in calls:
            fn = call.get("function") or {}
            name = fn.get("name", "")
            args = fn.get("arguments_parsed")
            if args is None:
                import json
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except (ValueError, TypeError):
                    args = {}
            settings.status = f"Running tool {name}… (step {iteration})"
            result = agent_tools.execute_tool(context, name, args)
            append_chat(context, "tool", f"{name}({args}) -> {result}")
            messages.append({"role": "tool", "tool_call_id": call.get("id", name),
                             "content": result})
    else:
        final_text = f"Stopped after {max_iterations} steps (limit). Ask me to continue if needed."
    append_chat(context, "assistant", final_text)
    settings.status = "Ready."
    return final_text
