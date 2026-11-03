"""Shared helpers: prompt building, texture storage, Blender image loading."""

from __future__ import annotations

import os
import re
import time

import bpy

from . import api_client, modal_client

_ICON_IDS = None


def safe_icon(name: str) -> str:
    """Return `name` if this Blender build knows the icon, else "NONE".

    Icon identifiers are not stable across Blender builds (5.4 alphas
    disagree on e.g. TIME vs RENDER_HISTORY). An unknown identifier makes
    UILayout.label()/operator() raise TypeError and aborts the whole panel
    draw, so an unrecognised icon degrades to no icon instead.
    """
    global _ICON_IDS
    if _ICON_IDS is None:
        try:
            fn = bpy.types.UILayout.bl_rna.functions["label"]
            param = [p for p in fn.parameters if p.identifier == "icon"][0]
            _ICON_IDS = {item.identifier for item in param.enum_items}
        except Exception:
            _ICON_IDS = set()
    return name if name in _ICON_IDS else "NONE"


TEXTURE_SUFFIX = (
    "seamless tileable PBR texture, flat top-down view, uniform even lighting, "
    "no perspective, no objects, no people, no text, no watermark, high detail"
)
STYLE_SUFFIXES = {
    "NONE": "",
    "PHOTOREAL": "photorealistic, natural colours, fine surface detail",
    "PBR_TEXTURE": TEXTURE_SUFFIX,
    "HAND_PAINTED": "hand-painted game texture, stylised, clean brushwork",
    "PIXEL_ART": "pixel-art texture, crisp pixels, limited palette",
}


def build_prompt(prompt: str, style: str, tileable: bool, for_texture: bool = True) -> str:
    """Append texture/style guidance without hiding the user's prompt."""
    parts = [prompt.strip()]
    suffix = STYLE_SUFFIXES.get(style, "")
    if suffix:
        parts.append(suffix)
    elif for_texture and tileable:
        parts.append(TEXTURE_SUFFIX)
    if for_texture and tileable and TEXTURE_SUFFIX not in ", ".join(parts):
        parts.append("edges wrap seamlessly on all sides")
    return ", ".join(part for part in parts if part)


def slugify(text: str, max_len: int = 32) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (text or "texture").lower()).strip("_")
    return (slug[:max_len] or "texture")


def _prefs():
    """Addon preferences, or None when running uninstalled (tests/scripts)."""
    try:
        return bpy.context.preferences.addons[__package__].preferences
    except (KeyError, AttributeError):
        return None


def textures_dir() -> str:
    """Where generated textures are written (created on demand)."""
    prefs = _prefs()
    if prefs is not None and prefs.output_dir:
        path = bpy.path.abspath(prefs.output_dir)
    elif bpy.data.filepath:
        path = os.path.join(os.path.dirname(bpy.path.abspath(bpy.data.filepath)),
                            "muse_textures")
    else:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated")
    os.makedirs(path, exist_ok=True)
    return path


def save_image_bytes(image_bytes: bytes, image_format: str, prompt: str) -> str:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"muse_{slugify(prompt)}_{stamp}.{image_format}"
    filepath = os.path.join(textures_dir(), filename)
    with open(filepath, "wb") as handle:
        handle.write(image_bytes)
    return filepath


def load_blender_image(filepath: str, name: str = "") -> bpy.types.Image:
    image = bpy.data.images.load(filepath, check_existing=False)
    if name:
        image.name = name
    try:
        image.pack()
    except RuntimeError:
        pass
    return image


def api_settings(context) -> tuple[str, str, str, str]:
    """Return (api_key, source, base_url, model) honouring Preferences + .env."""
    prefs = _prefs()
    extra_paths: list[str] = []
    explicit_key = ""
    base_url = api_client.DEFAULT_BASE_URL
    model = api_client.DEFAULT_MODEL
    if prefs is not None:
        explicit_key = prefs.api_key or ""
        base_url = prefs.base_url or base_url
        model = prefs.model or model
        if prefs.env_file:
            extra_paths.append(bpy.path.abspath(prefs.env_file))
    if bpy.data.filepath:
        extra_paths.append(os.path.join(
            os.path.dirname(bpy.path.abspath(bpy.data.filepath)), ".env"))
    key, source = api_client.resolve_api_key(explicit_key, extra_paths)
    return key, source, base_url, model


def modal_settings(context):
    """Return (ModalCredentials, app_name, cli_path) honouring Prefs + .env."""
    prefs = _prefs()
    extra_paths: list[str] = []
    explicit_id = explicit_secret = cli_path = ""
    app_name = modal_client.DEFAULT_APP_NAME
    if prefs is not None:
        explicit_id = prefs.modal_token_id or ""
        explicit_secret = prefs.modal_token_secret or ""
        cli_path = prefs.modal_cli_path or ""
        app_name = prefs.modal_app_name or app_name
        if prefs.env_file:
            extra_paths.append(bpy.path.abspath(prefs.env_file))
    if bpy.data.filepath:
        extra_paths.append(os.path.join(
            os.path.dirname(bpy.path.abspath(bpy.data.filepath)), ".env"))
    creds = modal_client.resolve_modal_credentials(
        explicit_id, explicit_secret, extra_paths)
    return creds, app_name, modal_client.find_modal_cli(
        bpy.path.abspath(cli_path) if cli_path else "")


def cloud_renders_dir() -> str:
    """Where cloud renders land (created on demand)."""
    if bpy.data.filepath:
        path = os.path.join(os.path.dirname(bpy.path.abspath(bpy.data.filepath)),
                            "muse_cloud_renders")
    else:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "cloud_renders")
    os.makedirs(path, exist_ok=True)
    return path


def splat_work_root() -> str:
    """Root folder for splat-segmentation jobs (created on demand).

    Each job gets its own timestamped subfolder with the exported points,
    rendered views, SAM label images and the worker log, so a run can be
    inspected or re-separated without re-running SAM.
    """
    if bpy.data.filepath:
        path = os.path.join(os.path.dirname(bpy.path.abspath(bpy.data.filepath)),
                            "muse_splat")
    else:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "generated", "splat_work")
    os.makedirs(path, exist_ok=True)
    return path


def active_mesh_object(context):
    obj = context.view_layer.objects.active
    if obj and obj.type == "MESH":
        return obj
    for candidate in context.selected_objects:
        if candidate.type == "MESH":
            return candidate
    return None


def _has_usable_uvs(obj) -> bool:
    layer = obj.data.uv_layers.active
    return bool(layer and obj.data.loops
                and len(layer.data) == len(obj.data.loops))


def _box_project_uvs(obj) -> bool:
    """Fallback UVs without operators (works in background mode)."""
    if obj.mode != "OBJECT":  # a failed unwrap attempt can leave Edit mode
        try:
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode="OBJECT")
        except RuntimeError:
            return False
    mesh = obj.data
    if not mesh.loops:
        return False
    layer = mesh.uv_layers.active
    if layer is None or len(layer.data) != len(mesh.loops):
        if layer is not None:
            mesh.uv_layers.remove(layer)
        layer = mesh.uv_layers.new(name="UVMap")
    coords = [v.co for v in mesh.vertices]
    lo = [min(c[i] for c in coords) for i in range(3)]
    span = [max(max(c[i] for c in coords) - lo[i], 1e-6) for i in range(3)]
    axes = [(1, 2), (0, 2), (0, 1)]  # dominant normal axis -> other two
    for poly in mesh.polygons:
        a, b = axes[max(range(3), key=lambda i: abs(poly.normal[i]))]
        for loop_index in poly.loop_indices:
            co = mesh.vertices[mesh.loops[loop_index].vertex_index].co
            layer.data[loop_index].uv = ((co[a] - lo[a]) / span[a],
                                         (co[b] - lo[b]) / span[b])
    return _has_usable_uvs(obj)


def ensure_uv_map(obj) -> bool:
    """Smart-unwrap when the mesh has no UV map. Returns True if it has UVs."""
    if obj.type != "MESH":
        return False
    if _has_usable_uvs(obj):
        return True
    layer = obj.data.uv_layers.active
    if layer is not None and len(layer.data) != len(obj.data.loops):
        obj.data.uv_layers.remove(layer)  # empty placeholder layer
    try:
        override = bpy.context.copy()
        override["object"] = obj
        override["active_object"] = obj
        override["selected_objects"] = [obj]
        override["selected_editable_objects"] = [obj]
        with bpy.context.temp_override(**override):
            bpy.ops.mesh.uv_texture_add()
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.uv.smart_project(angle_limit=66.0, island_margin=0.003)
            bpy.ops.object.mode_set(mode="OBJECT")
    except RuntimeError:
        pass
    return _has_usable_uvs(obj) or _box_project_uvs(obj)
