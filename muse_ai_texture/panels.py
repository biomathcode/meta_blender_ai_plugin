"""UI panels: 3D View sidebar, Shader editor and Geometry Nodes editor.

Consolidated layout (see design-plans/ui-consolidation.md): the main panel
is four boxes — Status, Create (Texture / Edit / Geometry Nodes variants),
Library & Apply (history + material + GN), Cloud Render (Image / Animation
variants). The chat shows only the last assistant response; the full
transcript stays in `scene.muse_chat` for the agent's context.
"""

import bpy
from bpy.types import Panel, UIList

from . import agent_loop
from . import nodes as nodes_mod
from . import utils


def _wrap(layout, text, icon="NONE", width=46):
    import textwrap
    icon = utils.safe_icon(icon)
    for line in str(text).splitlines() or [""]:
        chunks = textwrap.wrap(line, width=width) or [""]
        for chunk in chunks:
            layout.label(text=chunk, icon=icon if chunk == chunks[0] else "NONE")


def _md_inline(text: str) -> str:
    """Flatten inline Markdown for Blender labels (no rich text in UILayout).

    **bold** / *italic* markers are stripped (structure carries the meaning),
    `code` keeps its backticks so it still reads as code, [text](url) becomes
    'text (url)' truncated, and images ![alt](src) become '[image: alt]'.
    """
    import re
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"[image: \1]", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
                  lambda m: f"{m.group(1)} ({m.group(2)[:38]})", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"~~([^~]+)~~", r"\1", text)
    return text.strip()


def _draw_markdown(layout, text, width=46):
    """Render Markdown-ish agent output readably in a Blender panel.

    Blender labels have no styling, so structure does the work: headings
    get an icon + spacing, code fences are indented and never wrapped
    mid-token, lists get bullets with hanging indent, quotes are barred,
    and tables collapse to 'a · b · c' rows. The raw Markdown is never
    dumped verbatim — no stray **, ##, or ``` in the sidebar.
    """
    import re
    import textwrap

    def emit(content, icon="NONE", indent=0):
        prefix = "  " * indent
        avail = max(12, width - len(prefix) - 2)
        chunks = textwrap.wrap(content, width=avail) or [""]
        for i, chunk in enumerate(chunks):
            layout.label(text=prefix + chunk,
                         icon=utils.safe_icon(icon if i == 0 else "NONE"))

    in_code = False
    for raw in str(text).splitlines():
        line = raw.rstrip()
        if line.strip().startswith("```"):
            in_code = not in_code
            if in_code:
                layout.label(text="── code ──", icon=utils.safe_icon("CONSOLE"))
            continue
        if in_code:
            # Never wrap code: truncate visually, keep indentation.
            layout.label(text="│ " + line[: width + 8], icon=utils.safe_icon("NONE"))
            continue
        stripped = line.strip()
        if not stripped:
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            layout.label(text="")
            emit(_md_inline(heading.group(2)), icon="TEXT", indent=0)
            continue
        if re.match(r"^([-*_]){3,}$", stripped):
            layout.label(text="─" * 28)
            continue
        quote = re.match(r"^>\s?(.*)$", stripped)
        if quote:
            emit("│ " + _md_inline(quote.group(1)), indent=0)
            continue
        bullet = re.match(r"^[-*+]\s+(.*)$", stripped)
        if bullet:
            emit("• " + _md_inline(bullet.group(1)), indent=1)
            continue
        numbered = re.match(r"^(\d+)[.)]\s+(.*)$", stripped)
        if numbered:
            emit(f"{numbered.group(1)}. " + _md_inline(numbered.group(2)), indent=1)
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(re.match(r"^:?-+:?$", c) for c in cells):
                continue  # table separator row
            emit(" · ".join(_md_inline(c) for c in cells), indent=1)
            continue
        task = re.match(r"^\[([ xX])\]\s+(.*)$", stripped)
        if task:
            mark = "☑" if task.group(1).lower() == "x" else "☐"
            emit(f"{mark} " + _md_inline(task.group(2)), indent=1)
            continue
        emit(_md_inline(stripped))


# ---------------------------------------------------------------------------
# Main panel: Status / Create / Library & Apply / Cloud
# ---------------------------------------------------------------------------

def _status_box(layout, context):
    box = layout.box()
    box.label(text="Muse Harness — Status", icon=utils.safe_icon("IMAGE_DATA"))
    key, source, _url, _model = utils.api_settings(context)
    row = box.row()
    row.label(text="Muse Image connected" if key else "Muse Image: no API key",
              icon=utils.safe_icon("CHECKMARK" if key else "ERROR"))
    row.operator("muse.test_connection", text="Test", icon=utils.safe_icon("URL"))
    if not key:
        box.label(text="Add META_API_KEY to a .env file (addon or .blend folder)", icon=utils.safe_icon("INFO"))
        box.label(text="or paste it in Edit > Preferences > Add-ons.")
    creds, _app_name, cli_path = utils.modal_settings(context)
    row = box.row()
    row.label(text="Modal ready" if (creds.ok and cli_path) else "Modal not ready",
              icon=utils.safe_icon("CHECKMARK" if (creds.ok and cli_path) else "ERROR"))
    row.operator("muse.cloud_test", text="Test", icon=utils.safe_icon("URL"))
    obj = utils.active_mesh_object(context)
    box.label(text=f"Active mesh: {obj.name if obj else 'none'}"
                   + (f" · key: {source}" if key else ""))


def _create_box(layout, context, for_gn=False):
    scene = context.scene
    settings = scene.muse
    box = layout.box()
    box.label(text="Create — Muse Image", icon=utils.safe_icon("TEXTURE"))
    mode = "GN" if for_gn else settings.create_mode
    if not for_gn:
        row = box.row()
        row.prop(settings, "create_mode", expand=True)
    obj = utils.active_mesh_object(context)

    if mode == "EDIT":
        box.prop(settings, "edit_prompt", text="Change")
        box.prop(settings, "size")
        col = box.column()
        col.enabled = not settings.is_generating and bool(scene.muse_history)
        op = col.operator("muse.generate", text="Edit Last Image", icon=utils.safe_icon("FILE_REFRESH"))
        op.mode = "EDIT"
        op.apply_material = settings.auto_apply
        op.apply_gn = False
        if not scene.muse_history:
            box.label(text="Generate a texture first — it becomes the edit source.", icon=utils.safe_icon("INFO"))
    elif mode == "GN":
        if obj is not None:
            box.prop(obj.muse, "gn_prompt", text="Prompt")
            box.prop(obj.muse, "gn_tileable")
        else:
            box.label(text="Select a mesh object first.", icon=utils.safe_icon("ERROR"))
        box.prop(settings, "size")
        group = bpy.data.node_groups.get(nodes_mod.GN_GROUP_NAME)
        has_mod = bool(group and obj is not None and any(
            m.type == "NODES" and m.node_group == group for m in obj.modifiers))
        box.label(text=f"GN group {'ready' if group else 'not built yet'}"
                       f" · modifier on {obj.name}: {'yes' if has_mod else 'no'}"
                       if obj else f"GN group {'ready' if group else 'not built yet'}")
        col = box.column()
        col.enabled = not settings.is_generating
        op = col.operator("muse.generate", text="Generate for Geometry Nodes", icon=utils.safe_icon("PLAY"))
        op.mode = "GENERATE"
        op.apply_material = True
        op.apply_gn = True
        col.operator("muse.add_gn_modifier", text="Add GN Modifier Only", icon=utils.safe_icon("ADD"))
        box.label(text="Samples the image by position, stores muse_height,", icon=utils.safe_icon("INFO"))
        box.label(text="displaces along normals — subdivide for detail.")
    else:  # TEXTURE
        box.prop(settings, "prompt", text="Prompt")
        row = box.row(align=True)
        row.prop(settings, "size")
        row.prop(settings, "style")
        row = box.row(align=True)
        row.prop(settings, "tileable", toggle=True)
        row.prop(settings, "use_bump", toggle=True)
        row.prop(settings, "use_roughness", toggle=True)
        box.prop(settings, "auto_apply")
        col = box.column()
        col.enabled = not settings.is_generating
        op = col.operator("muse.generate", text="Generate Texture", icon=utils.safe_icon("PLAY"))
        op.mode = "GENERATE"
        op.apply_material = settings.auto_apply
        op.apply_gn = False
        op = col.operator("muse.generate", text="Generate + Geometry Nodes", icon=utils.safe_icon("GEOMETRY_NODES"))
        op.mode = "GENERATE"
        op.apply_material = True
        op.apply_gn = True

    if settings.is_generating:
        box.label(text="Generating with Muse Image…", icon=utils.safe_icon("SORTTIME"))
    _wrap(box, settings.status, icon="INFO")


def _library_box(layout, context):
    scene = context.scene
    settings = scene.muse
    box = layout.box()
    box.label(text=f"Library & Apply ({len(scene.muse_history)})", icon=utils.safe_icon("SORTTIME"))
    if scene.muse_history:
        layout.template_list("MUSE_UL_history", "", scene, "muse_history",
                             settings, "history_index", rows=4)
        row = box.row(align=True)
        op = row.operator("muse.apply_history", text="Apply", icon=utils.safe_icon("SHADING_TEXTURE"))
        op.index = -1
        op.apply_gn = False
        op = row.operator("muse.apply_history", text="Apply + GN", icon=utils.safe_icon("GEOMETRY_NODES"))
        op.index = -1
        op.apply_gn = True
        row = box.row(align=True)
        row.operator("muse.add_gn_modifier", text="Add GN Modifier", icon=utils.safe_icon("ADD"))
        if context.space_data and context.space_data.type == "NODE_EDITOR":
            row.operator("muse.add_gn_group_node", text="Group Node", icon=utils.safe_icon("NODE"))
    else:
        box.label(text="Generated textures will appear here.")
    row = box.row(align=True)
    row.operator("muse.open_textures_folder", text="Open Folder", icon=utils.safe_icon("FOLDER_REDIRECT"))
    row.operator("muse.clear_history", text="Clear", icon=utils.safe_icon("TRASH"))


def _cloud_box(layout, context):
    scene = context.scene
    cloud = scene.muse_cloud
    box = layout.box()
    box.label(text="Cloud Render — Modal", icon=utils.safe_icon("RENDER_STILL"))
    creds, _app_name, cli_path = utils.modal_settings(context)
    ready = creds.ok and bool(cli_path)
    if not creds.ok:
        box.label(text="Modal tokens missing. Add to a .env file", icon=utils.safe_icon("ERROR"))
        box.label(text="(addon folder or next to your .blend):")
        box.label(text="MODAL_TOKEN_ID=ak-…")
        box.label(text="MODAL_TOKEN_SECRET=as-…")
        box.label(text="Get tokens: modal.com/settings/tokens", icon=utils.safe_icon("URL"))
    elif not cli_path:
        box.label(text="Tokens OK — install the Modal CLI: pip install modal", icon=utils.safe_icon("INFO"))
    else:
        box.label(text=f"Tokens: {creds.source}", icon=utils.safe_icon("KEYINGSET"))
    camera = scene.camera
    render = scene.render
    box.label(text=f"Camera: {camera.name if camera else 'none — set an active camera'}",
              icon=utils.safe_icon("CAMERA_DATA" if camera else "ERROR"))
    box.label(text=f"{render.resolution_x}×{render.resolution_y} "
                   f"@ {render.resolution_percentage}% · {render.engine} · "
                   f"frames {scene.frame_start}–{scene.frame_end}",
              icon=utils.safe_icon("SCENE"))
    row = box.row()
    row.prop(cloud, "output_type", expand=True)
    row = box.row(align=True)
    row.prop(cloud, "use_gpu", toggle=True)
    if cloud.use_gpu:
        row.prop(cloud, "gpu", text="")
    if cloud.output_type == "ANIMATION":
        row = box.row(align=True)
        row.prop(cloud, "max_containers")
        row.prop(cloud, "frame_step")
    col = box.column()
    col.enabled = not cloud.is_rendering and camera is not None and ready
    if cloud.is_rendering:
        col.label(text="Rendering on Modal… (ESC cancels the wait)", icon=utils.safe_icon("SORTTIME"))
    still = cloud.output_type == "STILL"
    op = col.operator("muse.cloud_render",
                      text="Render Image on Modal" if still else "Render Animation on Modal",
                      icon=utils.safe_icon("RENDER_STILL" if still else "RENDER_ANIMATION"))
    op.mode = "STILL" if still else "ANIMATION"
    row = box.row(align=True)
    row.operator("muse.open_cloud_folder", text="Open Folder", icon=utils.safe_icon("FOLDER_REDIRECT"))
    if cloud.last_result:
        box.label(text=f"Last: {cloud.last_result}", icon=utils.safe_icon("CHECKMARK"))
    _wrap(box, cloud.status, icon="INFO")


def draw_muse_panel(layout, context, for_gn=False):
    _status_box(layout, context)
    _create_box(layout, context, for_gn=for_gn)
    _library_box(layout, context)
    _cloud_box(layout, context)


class MUSE_UL_history(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        row = layout.row(align=True)
        row.label(text=item.name or "texture", icon=utils.safe_icon("IMAGE_DATA"))
        row.label(text=item.created)


class MUSE_PT_view3d(Panel):
    bl_label = "Muse Harness"
    bl_idname = "MUSE_PT_view3d"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Muse Harness"
    bl_order = 1

    def draw(self, context):
        draw_muse_panel(self.layout, context)


class MUSE_PT_shader(Panel):
    bl_label = "Muse Harness"
    bl_idname = "MUSE_PT_shader"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Muse Harness"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return getattr(context.space_data, "tree_type", "") == "ShaderNodeTree"

    def draw(self, context):
        draw_muse_panel(self.layout, context)


class MUSE_PT_geometry(Panel):
    bl_label = "Muse Harness"
    bl_idname = "MUSE_PT_geometry"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Muse Harness"

    @classmethod
    def poll(cls, context):
        return getattr(context.space_data, "tree_type", "") == "GeometryNodeTree"

    def draw(self, context):
        draw_muse_panel(self.layout, context, for_gn=True)


# ---------------------------------------------------------------------------
# Chat: last response only, task-routed models, grouped quick actions
# ---------------------------------------------------------------------------

_QUICK_ACTIONS = (
    # label, prompt, task — Blender work runs on the lower Spark model.
    ("Scene info", "Inspect my scene and tell me what is in it.", "BLENDER"),
    ("Build + light", "Create a brick-textured cube with studio lighting and a camera, then frame it.", "BLENDER"),
    ("Texture selection", "Generate a Muse Image texture for my selected object (weathered stone), apply the PBR material and the Geometry Nodes displacement, then tell me the face count.", "BLENDER"),
    ("Optimize scene", "Optimize my whole scene for performance and report before/after.", "BLENDER"),
    ("Studio render", "Set up studio lighting and a camera for my selected object and render a PNG still locally.", "BLENDER"),
    # Cloud output: the agent must ask image-vs-animation and for .env tokens.
    ("Cloud render…", "I want to render this scene on Modal (cloud). First ask me ONE question — image (still) or animation/video — and wait for my answer. Then check Modal: if MODAL_TOKEN_ID or MODAL_TOKEN_SECRET is missing from Preferences/.env/environment, ask me to add exactly these two lines to a .env file next to my .blend (MODAL_TOKEN_ID=ak-... and MODAL_TOKEN_SECRET=as-..., from modal.com/settings/tokens) and STOP. If Modal is ready and I chose image, run bpy.ops.muse.cloud_render('INVOKE_DEFAULT', mode='STILL'); if animation, mode='ANIMATION'. Report the output file path when done.", "BLENDER"),
    # Site builds run on the higher Spark model.
    ("Product showcase site", "Turn my selected model into a web product showcase: optimize it for the web (Smart strategy — not decimate-only), bake Normal+AO detail onto the web copy, create a showcase animation (pick a variant that fits the product: TURNTABLE, HERO_REVEAL, FLOAT_SPIN or DIORAMA_ORBIT), seed the CMS content, then build the Three.js website. Tell me the strategy, face counts, bake result, folder, harness validation and the live URL / serve command. Reply in short Markdown: a heading, bullets, and a code block for the serve command.", "SITE"),
    ("Rewrite site copy", "Seed the showcase CMS if needed, then rewrite hero_title, hero_subtitle and the three feature titles/bodies in a punchier tone (English), and rebuild the website.", "SITE"),
)


def draw_chat_panel(layout, context):
    scene = context.scene
    agent = scene.muse_agent
    model = agent_loop.effective_model(agent)

    box = layout.box()
    box.label(text="Muse Agent (Spark + Blender MCP)", icon=utils.safe_icon("CONSOLE"))
    row = box.row(align=True)
    row.label(text="Running…" if agent.is_running else f"Idle · {model}",
              icon=utils.safe_icon("SORTTIME" if agent.is_running else "CHECKMARK"))
    row.operator("muse.mcp_health", text="Check MCP", icon=utils.safe_icon("URL"))
    _wrap(box, agent.status, icon="INFO")
    box.label(text=agent.mcp_status, icon=utils.safe_icon("INFO"))

    last = next((i for i in reversed(list(scene.muse_chat))
                 if i.role == "assistant"), None)
    chat_box = layout.box()
    chat_box.label(text=f"Last response · {len(scene.muse_chat)} messages in history",
                   icon=utils.safe_icon("TEXT"))
    if agent.is_running:
        chat_box.label(text="Working… tools and steps stay in history.", icon=utils.safe_icon("SORTTIME"))
    if last is not None:
        # Agent replies are Markdown — render structure, not raw markers.
        _draw_markdown(chat_box, last.text)
    else:
        chat_box.label(text="Ask: 'create a brick cube, light it, optimize the scene'…")

    input_box = layout.box()
    input_box.prop(agent, "task_type", expand=True)
    input_box.prop(agent, "input_text", text="Message")
    if agent.task_type == "CUSTOM":
        input_box.prop(agent, "spark_model")
    row = input_box.row(align=True)
    row.enabled = not agent.is_running
    row.operator("muse.chat_send", text="Send to Agent", icon=utils.safe_icon("PLAY"))
    row = input_box.row(align=True)
    row.operator("muse.chat_stop", text="Stop", icon=utils.safe_icon("SNAP_FACE"))
    row.operator("muse.chat_clear", text="Clear", icon=utils.safe_icon("TRASH"))

    quick = layout.box()
    quick.label(text="Quick actions", icon=utils.safe_icon("PRESET"))
    grid = quick.grid_flow(row_major=True, columns=2, align=True)
    for label, prompt, task in _QUICK_ACTIONS:
        op = grid.operator("muse.chat_quick", text=label)
        op.prompt = prompt
        op.task = task

    settings = layout.box()
    settings.label(text="Agent settings", icon=utils.safe_icon("PREFERENCES"))
    settings.prop(agent, "max_iterations")
    settings.prop(agent, "allow_code_execution")
    settings.prop(agent, "prefer_mcp")
    if not agent.allow_code_execution:
        settings.label(text="Python off: structured tools only.", icon=utils.safe_icon("ERROR"))


class MUSE_PT_chat(Panel):
    bl_label = "Muse Agent Chat"
    bl_idname = "MUSE_PT_chat"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Muse Harness"
    bl_order = 0

    def draw(self, context):
        draw_chat_panel(self.layout, context)


class MUSE_PT_chat_shader(Panel):
    bl_label = "Muse Agent Chat"
    bl_idname = "MUSE_PT_chat_shader"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Muse Harness"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return getattr(context.space_data, "tree_type", "") == "ShaderNodeTree"

    def draw(self, context):
        draw_chat_panel(self.layout, context)


# ---------------------------------------------------------------------------
# Product Showcase: Model & Animation / CMS / Website
# ---------------------------------------------------------------------------

class MUSE_UL_site_languages(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        row = layout.row(align=True)
        row.label(text=f"{item.code} — {item.label}", icon=utils.safe_icon("WORLD"))
        if item.is_default:
            row.label(text="default", icon=utils.safe_icon("CHECKMARK"))


class MUSE_UL_site_entries(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        row = layout.row(align=True)
        row.label(text=item.key, icon=utils.safe_icon("TEXT"))
        row.label(text=item.section)


def _site_server_state(site):
    """(is_live, url, detail) probed without blocking the UI for long.

    Import is local so the panel still draws when the harness module is
    being reloaded; the probe itself is a localhost socket + short HTTP
    read (bounded by site_harness timeouts).
    """
    try:
        from . import showcase as _showcase
        from . import site_harness as _harness
        port = int(site.site_port or 8000)
        probe = _harness.probe_site(port, _showcase.website_dir(bpy.context))
        return bool(probe.get("is_showcase")), probe.get("url", f"http://127.0.0.1:{port}/"), probe
    except Exception:  # noqa: BLE001 - panel must never fail to draw
        port = int(getattr(site, "site_port", 8000) or 8000)
        return False, f"http://127.0.0.1:{port}/", {}


def draw_showcase_panel(layout, context):
    scene = context.scene
    site = scene.muse_site
    obj = utils.active_mesh_object(context)

    box = layout.box()
    box.label(text="Website Category", icon=utils.safe_icon("WORLD"))
    box.prop(site, "site_variant", text="")
    if site.site_variant == "SHOPIFY":
        box.label(text="Store page: photo gallery + interactive 3D + 360°,", icon=utils.safe_icon("INFO"))
        box.label(text="price/buy panel + Shopify import files (shopify/).")
    elif site.site_variant == "CONFIGURATOR":
        box.label(text="Pick a finish → Blender-rendered 360° spin", icon=utils.safe_icon("INFO"))
        box.label(text="(cloudimage-360) + live 3D model below it.")
    else:
        box.label(text="Scroll showcase: GSAP-scrubbed Three.js product story.", icon=utils.safe_icon("INFO"))

    box = layout.box()
    box.label(text="Step 0 — Improve Prompt", icon=utils.safe_icon("TEXT"))
    box.prop(site, "prompt_raw", text="Brief")
    row = box.row(align=True)
    row.prop(site, "prompt_style", text="")
    row.prop(site, "prompt_audience", text="Audience")
    box.operator("muse.improve_site_prompt", text="Improve Prompt", icon=utils.safe_icon("PLAY"))
    if site.prompt_improved:
        _wrap(box, site.prompt_improved, icon="INFO")
    box.prop(site, "generate_ai_assets", toggle=True)
    if site.prompt_status:
        _wrap(box, site.prompt_status, icon="INFO")

    box = layout.box()
    box.label(text="Photos — Blender catalogue & 360° (viewport renders)", icon=utils.safe_icon("RENDER_STILL"))
    row = box.row(align=True)
    row.prop(site, "render_catalogue", toggle=True)
    row.prop(site, "image_resolution", text="")
    box.operator("muse.render_catalogue", text="Render Catalogue (hero/front/side/back/top/detail)", icon=utils.safe_icon("PLAY"))
    row = box.row(align=True)
    row.prop(site, "render_360", toggle=True)
    row.prop(site, "spin_frames")
    box.prop(site, "finish_options", text="Finishes")
    box.operator("muse.render_spin", text="Render 360° Spins (per finish)", icon=utils.safe_icon("PLAY"))
    box.prop(site, "hotspots", text="Hotspots")
    box.label(text="Sketchfab-style: markers + camera bookmarks, Shaded/Wireframe/", icon=utils.safe_icon("INFO"))
    box.label(text="X-Ray/Clay modes, explode slider and AR ship in the viewer.")
    box.prop(site, "enable_ar", toggle=True)
    if site.site_variant in ("SHOPIFY", "CONFIGURATOR"):
        sub = box.box()
        sub.label(text="Shopify", icon=utils.safe_icon("INFO"))
        row = sub.row(align=True)
        row.prop(site, "product_price", text="Price")
        row.prop(site, "product_currency", text="")
        row = sub.row(align=True)
        row.prop(site, "product_sku", text="SKU")
        row.prop(site, "product_vendor", text="Vendor")

    box = layout.box()
    box.label(text="Model — LODs (Low / Medium / High)", icon=utils.safe_icon("MOD_DECIM"))
    box.label(text=f"Selected mesh: {obj.name if obj else 'none'}"
                   + (f" ({len(obj.data.polygons)} faces)" if obj and obj.data else ""))
    box.prop(site, "product_object")
    box.label(text="Three versions are kept — no single crushed copy. The",
              icon=utils.safe_icon("INFO"))
    box.label(text="site visitor picks quality; High keeps full detail.")
    row = box.row(align=True)
    row.prop(site, "lod_high_ratio", text="High")
    row.prop(site, "lod_medium_ratio", text="Med")
    row.prop(site, "lod_low_ratio", text="Low")
    box.prop(site, "default_quality", text="Site Default")
    box.prop(site, "clean_first", toggle=True)
    box.operator("muse.optimize_selected", text="Create LODs (Low / Medium / High)", icon=utils.safe_icon("PLAY"))
    if site.lod_high_object:
        box.label(text=f"High: {site.lod_faces_high:,} · Med: {site.lod_faces_medium:,} · Low: {site.lod_faces_low:,} faces",
                  icon=utils.safe_icon("CHECKMARK"))

    box = layout.box()
    box.label(text="Bake — detail before render / GLB", icon=utils.safe_icon("TEXTURE"))
    box.label(text="Bakes Normal + AO onto Medium + Low LODs (High is full detail).", icon=utils.safe_icon("INFO"))
    box.label(text="Run before rendering the product or building the GLBs.")
    box.prop(site, "bake_enabled", toggle=True)
    row = box.row(align=True)
    row.prop(site, "bake_resolution", text="Res")
    row.prop(site, "bake_margin")
    row = box.row(align=True)
    row.prop(site, "bake_normal", toggle=True)
    row.prop(site, "bake_ao", toggle=True)
    box.prop(site, "bake_cage_extrusion")
    col = box.column()
    col.enabled = bool(site.bake_enabled)
    col.operator("muse.bake_product", text="Bake Detail onto Medium / Low LODs", icon=utils.safe_icon("PLAY"))
    if site.bake_status:
        _wrap(box, site.bake_status, icon="INFO")

    box = layout.box()
    box.label(text="Animation — showcase variants", icon=utils.safe_icon("PLAY"))
    row = box.row(align=True)
    row.prop(site, "animation_style", text="")
    row.prop(site, "animation_frames")
    box.operator("muse.create_showcase_animation", text="Create Showcase Animation", icon=utils.safe_icon("PLAY"))
    box.label(text="Baked in Blender, exported in the GLB, scrubbed by scroll.", icon=utils.safe_icon("INFO"))

    box = layout.box()
    box.label(text="CMS — content & languages (stored in this .blend)", icon=utils.safe_icon("TEXT"))
    box.prop(site, "brand_name")
    row = box.row(align=True)
    row.operator("muse.cms_seed", text="Seed Default Content (en + hi)", icon=utils.safe_icon("ADD"))
    box.label(text=f"Languages ({len(scene.muse_site_languages)})", icon=utils.safe_icon("WORLD"))
    if scene.muse_site_languages:
        layout.template_list("MUSE_UL_site_languages", "", scene,
                             "muse_site_languages", site, "language_index", rows=3)
        row = box.row(align=True)
        row.operator("muse.cms_set_default_language", text="Make Default")
        row.operator("muse.cms_remove_language", text="Remove", icon=utils.safe_icon("TRASH"))
    row = box.row(align=True)
    row.prop(site, "new_language_code", text="Code")
    row.prop(site, "new_language_label", text="Label")
    box.operator("muse.cms_add_language", text="Add Language", icon=utils.safe_icon("ADD"))
    box.label(text=f"Entries ({len(scene.muse_site_entries)})", icon=utils.safe_icon("TEXT"))
    if scene.muse_site_entries:
        layout.template_list("MUSE_UL_site_entries", "", scene,
                             "muse_site_entries", site, "entry_index", rows=5)
        row = box.row(align=True)
        row.operator("muse.cms_remove_entry", text="Remove Entry", icon=utils.safe_icon("TRASH"))
        index = site.entry_index
        if 0 <= index < len(scene.muse_site_entries):
            entry = scene.muse_site_entries[index]
            sub = box.box()
            sub.label(text=f"Edit '{entry.key}' ({entry.section})", icon=utils.safe_icon("GREASEPENCIL"))
            sub.prop(entry, "section")
            if not entry.translations:
                sub.label(text="Seed content or add a language to edit text.", icon=utils.safe_icon("INFO"))
            for translation in entry.translations:
                sub.prop(translation, "text", text=translation.lang)
            sub.label(text="Blank = falls back to the default language.", icon=utils.safe_icon("INFO"))
    row = box.row(align=True)
    row.prop(site, "new_entry_key", text="Key")
    row.prop(site, "new_entry_section", text="Section")
    box.operator("muse.cms_add_entry", text="Add Entry", icon=utils.safe_icon("ADD"))

    box = layout.box()
    box.label(text="Three.js Lighting & Presentation", icon=utils.safe_icon("LIGHT_SUN"))
    box.prop(site, "lighting_preset", text="Preset")
    row = box.row(align=True)
    row.prop(site, "env_intensity")
    row.prop(site, "exposure")
    row = box.row(align=True)
    row.prop(site, "diorama_mode", toggle=True)
    row.prop(site, "auto_rotate_idle", toggle=True)
    box.label(text="IBL (RoomEnvironment) + 3-point rig + soft shadows.", icon=utils.safe_icon("INFO"))
    box.label(text="Diorama locks the camera to isometric + adds a plinth.")

    box = layout.box()
    box.label(text="Three.js Website (GSAP ScrollTrigger)", icon=utils.safe_icon("WORLD"))
    box.prop(site, "accent_color")
    row = box.row(align=True)
    row.prop(site, "dark_background", toggle=True)
    row.prop(site, "scroll_scrub", toggle=True)
    box.prop(site, "export_dir")
    row = box.row(align=True)
    row.prop(site, "site_port")
    row.prop(site, "build_validate", toggle=True)
    box.operator("muse.build_website", text="Build Website (prompt → bake → GLBs → photos/360 → site)", icon=utils.safe_icon("PLAY"))
    row = box.row(align=True)
    row.operator("muse.open_website_folder", text="Open Folder", icon=utils.safe_icon("FOLDER_REDIRECT"))
    if site.last_site_dir:
        box.label(text=f"Last build: {site.last_site_dir}", icon=utils.safe_icon("CHECKMARK"))
    # --- Harness: is the site actually running? Quick link to its port. ---
    is_live, live_url, _probe = _site_server_state(site)
    box = layout.box()
    if is_live:
        box.label(text="● Site is LIVE", icon=utils.safe_icon("CHECKMARK"))
        box.label(text=live_url, icon=utils.safe_icon("URL"))
        row = box.row(align=True)
        row.operator("muse.open_site_url", text="Open Site in Browser", icon=utils.safe_icon("URL"))
        row.operator("muse.check_site_server", text="Re-check", icon=utils.safe_icon("FILE_REFRESH"))
    else:
        box.label(text="○ Site is not running", icon=utils.safe_icon("INFO"))
        box.label(text=f"Quick link (after starting): {live_url}", icon=utils.safe_icon("URL"))
        box.label(text=f"Start: python3 serve.py {int(site.site_port or 8000)}  (in the site folder)")
        row = box.row(align=True)
        row.operator("muse.check_site_server", text="Check If Site Is Running", icon=utils.safe_icon("FILE_REFRESH"))
        row.operator("muse.open_site_url", text="Open Link", icon=utils.safe_icon("URL"))
    _wrap(box, site.status, icon="INFO")


def draw_splat_panel(layout, context):
    from . import splat_operators

    scene = context.scene
    settings = scene.muse_splat
    source = splat_operators._resolve_splat_object(context, settings)

    box = layout.box()
    box.label(text="Gaussian Splat — SAM 3.1 Segmentation", icon=utils.safe_icon("POINTCLOUD_DATA"))
    if source is not None:
        box.label(text=f"Splat: {source.name} · {len(source.data.points):,} Gaussians",
                  icon=utils.safe_icon("CHECKMARK"))
    else:
        box.label(text="Splat: none — import an .spz or select a splat object",
                  icon=utils.safe_icon("INFO"))
    row = box.row(align=True)
    row.prop(settings, "spz_path", text="")
    row.operator("muse.splat_import", text="Import SPZ", icon=utils.safe_icon("IMPORT"))
    if source is not None:
        box.prop(settings, "source_object", text="Object")

    box.prop(settings, "prompts", text="Objects")
    box.label(text="Only these objects are segmented (SAM 3.1, Meta API,",
              icon=utils.safe_icon("INFO"))
    box.label(text="your Meta key). E.g. sand, rock, shell, vegetation.")
    key, _source, _url, _model = utils.api_settings(context)
    box.label(text="Meta key ready for SAM 3.1" if key else "No Meta key — add META_API_KEY (.env / Preferences)",
              icon=utils.safe_icon("CHECKMARK" if key else "ERROR"))

    row = box.row(align=True)
    row.prop(settings, "num_views")
    row.prop(settings, "resolution", text="")
    row = box.row(align=True)
    row.prop(settings, "sam_threshold")
    row.prop(settings, "min_votes")
    row = box.row(align=True)
    row.prop(settings, "min_cluster")
    row.prop(settings, "keep_background", toggle=True)

    col = box.column()
    col.enabled = not settings.is_processing
    col.operator("muse.splat_segment", text="Segment & Separate",
                 icon=utils.safe_icon("PLAY"))
    if settings.is_processing:
        box.label(text="Working… (ESC in the viewport cancels)", icon=utils.safe_icon("SORTTIME"))
    row = box.row(align=True)
    row.operator("muse.splat_separate_again", text="Separate Again", icon=utils.safe_icon("MOD_EDGESPLIT"))
    row.operator("muse.splat_open_workdir", text="Job Folder", icon=utils.safe_icon("FOLDER_REDIRECT"))
    _wrap(box, settings.status, icon="INFO")
    if settings.last_summary:
        _wrap(box, settings.last_summary, icon="CHECKMARK")

    setup = layout.box()
    setup.label(text="Splat Worker (renders views, votes; SAM on Meta API)", icon=utils.safe_icon("PREFERENCES"))
    _python, source_label = splat_operators.worker_python(context)
    setup.label(text=f"Python: {source_label}", icon=utils.safe_icon("CONSOLE"))
    row = setup.row(align=True)
    row.enabled = not settings.is_processing
    row.operator("muse.splat_check_setup", text="Check Setup", icon=utils.safe_icon("URL"))
    row.operator("muse.splat_setup_worker", text="Create Worker Env", icon=utils.safe_icon("ADD"))
    setup.label(text="Light worker only (numpy + parser). SAM 3.1 runs on",
                icon=utils.safe_icon("INFO"))
    setup.label(text="the Meta API — no weights, no GPU, no HF token.",
                icon=utils.safe_icon("INFO"))


class MUSE_PT_splat(Panel):
    bl_label = "Gaussian Splat — SAM 3.1 Segmentation"
    bl_idname = "MUSE_PT_splat"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Muse Harness"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 3

    def draw(self, context):
        draw_splat_panel(self.layout, context)


class MUSE_PT_showcase(Panel):
    bl_label = "Product Showcase (Web)"
    bl_idname = "MUSE_PT_showcase"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Muse Harness"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 2

    def draw(self, context):
        draw_showcase_panel(self.layout, context)


classes = (MUSE_UL_history, MUSE_PT_view3d, MUSE_PT_shader, MUSE_PT_geometry,
           MUSE_UL_site_languages, MUSE_UL_site_entries, MUSE_PT_showcase,
           MUSE_PT_splat, MUSE_PT_chat, MUSE_PT_chat_shader)


def _add_gn_node_button(self, context):
    if getattr(context.space_data, "tree_type", "") == "GeometryNodeTree":
        self.layout.operator("muse.add_gn_group_node", text="Muse GN Texture",
                             icon=utils.safe_icon("IMAGE_DATA"))


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.NODE_MT_add.append(_add_gn_node_button)


def unregister():
    bpy.types.NODE_MT_add.remove(_add_gn_node_button)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
