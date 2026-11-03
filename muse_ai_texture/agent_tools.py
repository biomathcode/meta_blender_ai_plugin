"""Blender tool registry for the Muse Spark agent.

Every tool is a validated bpy operation returning a compact string result.
Structured tools are preferred; `execute_blender_python` (gated by the
agent's Allow Code Execution setting) covers everything else, which is how
the agent can perform any Blender action. Tools always run on Blender's
main thread (called from the agent loop / modal operator).
"""

from __future__ import annotations

import json
import os

import bpy

from . import api_client, mcp_bridge, nodes, showcase, skills, utils
from . import spark_client  # noqa: F401  (keeps the agent stack imported together)

MAX_RESULT = 3000


def _obj(name: str):
    return bpy.data.objects.get(name) if name else bpy.context.view_layer.objects.active


def _active_or(name: str = ""):
    obj = _obj(name)
    if obj is None:
        raise ValueError(f"Object not found: {name or '(no active object)'}")
    return obj


def _vec(value, default=(0.0, 0.0, 0.0)):
    try:
        return tuple(float(v) for v in (value or default))[:3]
    except (TypeError, ValueError):
        return tuple(default)


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------

def get_scene_info(context, **_args):
    scene = context.scene
    counts: dict[str, int] = {}
    faces = verts = 0
    for obj in scene.objects:
        counts[obj.type] = counts.get(obj.type, 0) + 1
        if obj.type == "MESH" and obj.data:
            faces += len(obj.data.polygons)
            verts += len(obj.data.vertices)
    return (f"Scene '{scene.name}': {len(scene.objects)} objects {counts}, "
            f"{verts} verts, {faces} faces, frames {scene.frame_start}-{scene.frame_end}, "
            f"engine {scene.render.engine}, "
            f"{len(bpy.data.materials)} materials, {len(bpy.data.images)} images, "
            f"file: {bpy.data.filepath or '(unsaved)'}.")


def list_objects(context, **_args):
    lines = []
    for obj in context.scene.objects:
        extra = ""
        if obj.type == "MESH" and obj.data:
            extra = f", {len(obj.data.polygons)} faces"
        lines.append(f"- {obj.name} [{obj.type}{extra}] loc={tuple(round(v, 2) for v in obj.location)}")
    return "\n".join(lines)[:MAX_RESULT] or "(scene is empty)"


def get_object_info(context, object_name="", **_args):
    obj = _active_or(object_name)
    info = {"name": obj.name, "type": obj.type,
            "location": [round(v, 3) for v in obj.location],
            "scale": [round(v, 3) for v in obj.scale],
            "modifiers": [(m.name, m.type) for m in obj.modifiers],
            "materials": [s.material.name for s in obj.material_slots if s.material]}
    if obj.type == "MESH" and obj.data:
        info.update(vertices=len(obj.data.vertices), faces=len(obj.data.polygons),
                    uv_layers=[u.name for u in obj.data.uv_layers])
    return json.dumps(info)[:MAX_RESULT]


# ---------------------------------------------------------------------------
# Objects / modelling
# ---------------------------------------------------------------------------

def create_primitive(context, kind="CUBE", size=2.0, location=None, name="", **_args):
    creators = {
        "CUBE": bpy.ops.mesh.primitive_cube_add,
        "SPHERE": bpy.ops.mesh.primitive_uv_sphere_add,
        "CYLINDER": bpy.ops.mesh.primitive_cylinder_add,
        "CONE": bpy.ops.mesh.primitive_cone_add,
        "TORUS": bpy.ops.mesh.primitive_torus_add,
        "PLANE": bpy.ops.mesh.primitive_plane_add,
        "MONKEY": bpy.ops.mesh.primitive_monkey_add,
    }
    creator = creators.get(str(kind).upper(), bpy.ops.mesh.primitive_cube_add)
    kwargs = {"location": _vec(location)}
    if str(kind).upper() in ("CUBE", "PLANE"):
        kwargs["size"] = float(size)
    elif str(kind).upper() in ("SPHERE", "CYLINDER", "CONE"):
        kwargs["radius"] = float(size) / 2.0
        if str(kind).upper() in ("CYLINDER", "CONE"):
            kwargs["depth"] = float(size)
    creator(**kwargs)
    obj = context.view_layer.objects.active
    if name:
        obj.name = name
    return f"Created {obj.name} ({obj.type}) at {tuple(round(v, 2) for v in obj.location)}."


def transform_object(context, object_name="", location=None, rotation_deg=None,
                     scale=None, **_args):
    obj = _active_or(object_name)
    if location is not None:
        obj.location = _vec(location)
    if rotation_deg is not None:
        import math
        obj.rotation_euler = tuple(math.radians(float(a)) for a in _vec(rotation_deg))
    if scale is not None:
        obj.scale = _vec(scale, (1, 1, 1))
    return f"{obj.name}: loc={tuple(round(v, 2) for v in obj.location)}, scale={tuple(round(v, 2) for v in obj.scale)}."


def delete_object(context, object_name="", **_args):
    obj = _active_or(object_name)
    name = obj.name
    bpy.data.objects.remove(obj, do_unlink=True)
    return f"Deleted {name}."


def duplicate_object(context, object_name="", **_args):
    obj = _active_or(object_name)
    copy = obj.copy()
    if obj.data and hasattr(obj.data, "copy"):
        try:
            copy.data = obj.data.copy()
        except RuntimeError:
            pass
    context.collection.objects.link(copy)
    return f"Duplicated {obj.name} -> {copy.name}."


def add_modifier(context, object_name="", modifier_type="SUBSURF", **args):
    obj = _active_or(object_name)
    mod = obj.modifiers.new(name=str(modifier_type).title(), type=str(modifier_type).upper())
    for prop in ("levels", "count", "thickness", "width", "factor", "ratio"):
        if prop in args:
            try:
                setattr(mod, prop, args[prop])
            except (AttributeError, TypeError, ValueError):
                pass
    if mod.type == "DECIMATE" and "ratio" in args:
        mod.ratio = float(args["ratio"])
    return f"Added {mod.type} modifier to {obj.name}."


def apply_modifier(context, object_name="", modifier_name="", **_args):
    obj = _active_or(object_name)
    if not obj.modifiers:
        return f"{obj.name} has no modifiers."
    mod = obj.modifiers.get(modifier_name) if modifier_name else obj.modifiers[0]
    if mod is None:
        return f"No modifier named {modifier_name} on {obj.name}."
    override = context.copy()
    override["object"] = obj
    override["active_object"] = obj
    with context.temp_override(**override):
        bpy.ops.object.modifier_apply(modifier=mod.name)
    return f"Applied modifier {mod.name} on {obj.name}."


# ---------------------------------------------------------------------------
# Materials / textures
# ---------------------------------------------------------------------------

def create_material(context, name="Agent Material", color=None, metallic=0.0,
                    roughness=0.5, assign_to="", **_args):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    principled = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if principled is not None:
        rgba = list(_vec(color, (0.8, 0.8, 0.8))) + [1.0]
        principled.inputs["Base Color"].default_value = rgba
        principled.inputs["Metallic"].default_value = float(metallic)
        principled.inputs["Roughness"].default_value = float(roughness)
    if assign_to:
        obj = _active_or(assign_to)
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)
        return f"Created material {mat.name} and assigned it to {obj.name}."
    return f"Created material {mat.name}."


def generate_texture(context, prompt="", object_name="", tileable=True, **_args):
    from . import operators as _ops  # reuse the apply pipeline

    key, _source, base_url, model = utils.api_settings(context)
    if not key:
        return "ERROR: no Meta API key (META_API_KEY in .env or Preferences)."
    full = utils.build_prompt(prompt or context.scene.muse.prompt, "PBR_TEXTURE", tileable)
    result = api_client.generate_image(full, key, size=context.scene.muse.size,
                                       base_url=base_url, model="muse-image-1.0")
    if object_name:
        obj = _obj(object_name)
        if obj is not None:
            previous = context.view_layer.objects.active
            context.view_layer.objects.active = obj
            try:
                detail = _ops._apply_generated_image(context, result, full, True, False)
            finally:
                context.view_layer.objects.active = previous
            return f"Generated Muse texture and applied it: {detail}"
    return _ops._apply_generated_image(context, result, full, True, False)


def add_gn_texture(context, object_name="", strength=0.08, texture_scale=1.0, **_args):
    obj = _active_or(object_name)
    image = None
    if context.scene.muse_history:
        image = bpy.data.images.get(context.scene.muse_history[-1].image_name)
    mod = nodes.add_gn_modifier(obj, image=image, strength=float(strength),
                                texture_scale=float(texture_scale))
    return (f"Muse GN Texture modifier '{mod.name}' on {obj.name} "
            f"(image: {image.name if image else 'none yet — generate a texture first'}). "
            "Add a Subdivision modifier before it for visible displacement.")


# ---------------------------------------------------------------------------
# Optimization / size reduction
# ---------------------------------------------------------------------------

def analyze_scene(context, **_args):
    meshes = sorted(
        ((len(o.data.polygons), o.name) for o in context.scene.objects
         if o.type == "MESH" and o.data), reverse=True)
    total_faces = sum(count for count, _n in meshes)
    big_images = [(f"{i.size[0]}x{i.size[1]}", i.name) for i in bpy.data.images
                  if i.size[0] > 1024]
    top = ", ".join(f"{name} ({count} faces)" for count, name in meshes[:6])
    return (f"{len(meshes)} meshes, {total_faces} faces total. Largest: {top or 'none'}. "
            f"{len(big_images)} images over 1024px: {big_images[:6]}. "
            f"Orphans likely: {len([m for m in bpy.data.materials if m.users == 0])} unused materials.")


def optimize_object(context, object_name="", ratio=0.5, **_args):
    obj = _active_or(object_name)
    if obj.type != "MESH":
        return f"{obj.name} is not a mesh."
    before = len(obj.data.polygons)
    mod = obj.modifiers.new("Muse Decimate", "DECIMATE")
    mod.ratio = max(0.02, min(1.0, float(ratio)))
    override = context.copy()
    override["object"] = obj
    override["active_object"] = obj
    with context.temp_override(**override):
        bpy.ops.object.modifier_apply(modifier=mod.name)
    return f"{obj.name}: {before} -> {len(obj.data.polygons)} faces (ratio {ratio})."


def clean_mesh(context, object_name="", **_args):
    obj = _active_or(object_name)
    if obj.type != "MESH":
        return f"{obj.name} is not a mesh."
    override = context.copy()
    override["object"] = obj
    override["active_object"] = obj
    override["selected_objects"] = [obj]
    override["selected_editable_objects"] = [obj]
    with context.temp_override(**override):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.remove_doubles(threshold=0.0001)
        bpy.ops.mesh.delete_loose()
        bpy.ops.object.mode_set(mode="OBJECT")
    return f"Cleaned {obj.name} (merged by distance, deleted loose geometry)."


def resize_textures(context, max_size=1024, **_args):
    changed = []
    for image in bpy.data.images:
        width, height = image.size[0], image.size[1]
        if width > max_size or height > max_size:
            scale = max_size / max(width, height)
            image.scale(int(width * scale), int(height * scale))
            changed.append(f"{image.name}: {width}x{height} -> {image.size[0]}x{image.size[1]}")
    return "Resized: " + ("; ".join(changed) if changed else "nothing over the limit.")


def purge_orphans(context, **_args):
    for _ in range(3):
        try:
            bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True,
                                           do_recursive=True)
        except RuntimeError:
            break
    return (f"Purged orphans. Now: {len(bpy.data.materials)} materials, "
            f"{len(bpy.data.images)} images, {len(bpy.data.meshes)} meshes.")


def optimize_scene(context, decimate_ratio=0.5, face_threshold=20000,
                   texture_max=1024, **_args):
    before_faces = sum(len(o.data.polygons) for o in context.scene.objects
                       if o.type == "MESH" and o.data)
    touched = []
    for obj in list(context.scene.objects):
        if obj.type == "MESH" and obj.data and len(obj.data.polygons) > int(face_threshold):
            touched.append(optimize_object(context, object_name=obj.name,
                                           ratio=float(decimate_ratio)).split(":")[0])
    resized = resize_textures(context, max_size=int(texture_max))
    purged = purge_orphans(context)
    after_faces = sum(len(o.data.polygons) for o in context.scene.objects
                      if o.type == "MESH" and o.data)
    return (f"Optimized {len(touched)} meshes {touched[:6]}. Faces {before_faces} -> {after_faces}. "
            f"{resized} {purged}")


# ---------------------------------------------------------------------------
# Scene / render / files
# ---------------------------------------------------------------------------

def add_light(context, light_type="AREA", location=None, energy=1000.0, name="", **_args):
    data = bpy.data.lights.new(name or str(light_type).title(), str(light_type).upper())
    data.energy = float(energy)
    obj = bpy.data.objects.new(data.name, data)
    obj.location = _vec(location, (3, -3, 4))
    context.collection.objects.link(obj)
    return f"Added {light_type} light {obj.name} (energy {energy})."


def add_camera(context, location=None, name="Agent Camera", make_active=True, **_args):
    data = bpy.data.cameras.new(name)
    obj = bpy.data.objects.new(name, data)
    obj.location = _vec(location, (4, -6, 3))
    obj.rotation_euler = (1.1, 0, 0.6)
    context.collection.objects.link(obj)
    if make_active:
        context.scene.camera = obj
    return f"Added camera {obj.name}."


def set_render_settings(context, engine="", resolution_x=0, resolution_y=0, samples=0, **_args):
    scene = context.scene
    if engine:
        try:
            scene.render.engine = str(engine).upper()
        except TypeError:
            return f"Unknown render engine '{engine}'. Try CYCLES or BLENDER_EEVEE_NEXT."
    if resolution_x:
        scene.render.resolution_x = int(resolution_x)
    if resolution_y:
        scene.render.resolution_y = int(resolution_y)
    if samples and hasattr(scene, "cycles"):
        scene.cycles.samples = int(samples)
    return (f"Render: {scene.render.engine}, {scene.render.resolution_x}x"
            f"{scene.render.resolution_y}, Cycles samples "
            f"{getattr(scene.cycles, 'samples', 'n/a')}.")


def render_image(context, filepath="", **_args):
    if context.scene.camera is None:
        return "ERROR: no active camera. Add one with add_camera first."
    path = bpy.path.abspath(filepath) if filepath else os.path.join(utils.textures_dir(), "agent_render.png")
    context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return f"Rendered to {path} ({os.path.getsize(path) if os.path.exists(path) else 0} bytes)."


def save_file(context, filepath="", **_args):
    path = bpy.path.abspath(filepath) if filepath else bpy.data.filepath
    if not path:
        return "ERROR: no filepath. Save the .blend once or pass a path."
    bpy.ops.wm.save_as_mainfile(filepath=path, compress=True)
    size = os.path.getsize(path) / (1024 * 1024)
    return f"Saved {path} ({size:.2f} MB, compressed)."


def export_glb(context, filepath="", **_args):
    if not filepath:
        return "ERROR: pass a .glb filepath."
    path = bpy.path.abspath(filepath)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_apply=False,
                              export_animations=True, export_cameras=True,
                              export_lights=False,
                              export_draco_mesh_compression_enable=False)
    size = os.path.getsize(path) / (1024 * 1024) if os.path.exists(path) else 0
    return f"Exported {path} ({size:.2f} MB, modifiers not applied, no Draco)."


def keyframe_object(context, object_name="", frame=1, data_path="location", **_args):
    obj = _active_or(object_name)
    obj.keyframe_insert(data_path=data_path, frame=int(frame))
    return f"Keyframed {obj.name}.{data_path} at frame {frame}."


def set_frame_range(context, frame_start=1, frame_end=250, **_args):
    context.scene.frame_start = int(frame_start)
    context.scene.frame_end = int(frame_end)
    return f"Frame range {frame_start}-{frame_end}."


# ---------------------------------------------------------------------------
# Skills / code / MCP
# ---------------------------------------------------------------------------

def optimize_for_web(context, object_name="", ratio=0.35, strategy="", **_args):
    obj = _active_or(object_name)
    result = showcase.optimize_product(context, obj=obj)
    tiers = ", ".join(f"{level} {info['faces']}" for level, info
                      in result["lods"].items())
    return (f"Created LODs from {result['source']} "
            f"({result['faces_before']} faces): {tiers} (original kept). "
            f"High keeps full detail — no single crushed copy. The site "
            f"exports all three GLBs and visitors pick Low/Medium/High. "
            f"Next: bake_product_maps (Medium/Low), then "
            f"create_showcase_animation.")


def bake_product_maps_tool(context, object_name="", **_args):
    result = showcase.bake_lod_maps(context)
    return (f"Baked onto Medium/Low LODs: {result.get('detail')} "
            f"Run this before render_image / export_glb / build_website "
            f"so the detail ships (High keeps full geometry).")


def create_showcase_animation_tool(context, object_name="", style="TURNTABLE",
                                   frames=120, **_args):
    obj = _obj(object_name) if object_name else showcase.product_object(context)
    result = showcase.create_showcase_animation(
        context, obj=obj, style=str(style).upper(), frames=int(frames))
    return (f"Baked showcase animation '{result['animation']}' ({result.get('style')}) "
            f"on {result['object']} ({result['frames']} frames); it exports in the "
            f"GLB and is scrubbed by scroll.")


def seed_cms_tool(context, product_name="", **_args):
    result = showcase.seed_cms(context, product_name)
    showcase.ensure_translation_slots(context)
    missing = showcase.web_cms.missing_translations(
        showcase.cms_entries(context), showcase.cms_languages(context))
    return (f"CMS seeded: {result['languages']} languages, {result['entries']} entries. "
            f"Missing translations (fall back on site): {missing or 'none'}.")


def set_cms_text_tool(context, key="", lang="en", text="", **_args):
    if not key:
        return "ERROR: pass a CMS key, e.g. hero_title."
    return showcase.set_cms_text(context, str(key), str(lang), str(text))


def improve_prompt_tool(context, brief="", style="ECOMMERCE", **_args):
    site = context.scene.muse_site
    if brief:
        site.prompt_raw = str(brief)
    if style:
        site.prompt_style = str(style).upper()
    result = showcase.improve_site_prompt(context)
    return (f"Improved prompt ({result['style']}): {result['improved']} "
            f"Hero: {result['hero_title']}")


def render_catalogue_tool(context, **_args):
    images = showcase.render_catalogue_images(context, showcase.website_dir(context))
    return f"Catalogue rendered: {len(images)} images ({', '.join(i['id'] for i in images)})."


def build_website_tool(context, variant="", **_args):
    if variant:
        context.scene.muse_site.site_variant = str(variant).upper()
    result = showcase.build_website(context)
    problems = result.get("validation") or []
    live = "LIVE at " + result["url"] if result.get("running") else "not serving yet"
    return (f"{result.get('variant')} website built: {result['index']} (GLB {result['glb_kb']} KB, "
            f"{len(result.get('images') or [])} catalogue images, {len(result.get('spins') or [])} 360 spins, "
            f"{result['languages']} languages, {result['entries']} CMS entries, "
            f"animation {result['animation'] or 'none'}, bake {(result.get('bake') or {}).get('baked')}). "
            f"Harness: {'OK' if not problems else 'problems: ' + '; '.join(problems)}. "
            f"Site {live}. Serve with: cd {result['site_dir']} && python3 serve.py {result['port']} "
            f"then open {result['url']}")


def check_site_tool(context, **_args):
    from . import site_harness
    site = context.scene.muse_site
    port = int(getattr(site, "site_port", 8000) or 8000)
    probe = site_harness.probe_site(port, showcase.website_dir(context))
    problems = site_harness.validate_site(showcase.website_dir(context))
    if probe["is_showcase"]:
        return f"Site is LIVE at {probe['url']} (HTTP {probe['status']}). Validation: {'OK' if not problems else problems}."
    if probe["running"]:
        return (f"Port {port} is serving other content, not this showcase. "
                f"Validation: {'OK' if not problems else problems}. "
                f"Start ours on another port, e.g. python3 serve.py {site_harness.find_free_port(port + 1)}.")
    return (f"Site is NOT running. Validation: {'OK' if not problems else problems}. "
            f"Start it: cd {showcase.website_dir(context)} && python3 serve.py {port} "
            f"then open http://127.0.0.1:{port}/")


def list_skills_tool(context, **_args):
    return skills.list_skills_text()[:MAX_RESULT]


def get_skill_tool(context, skill_id="", **_args):
    return skills.get_skill(skill_id)[:MAX_RESULT * 2]


def mcp_health(context, **_args):
    available = mcp_bridge.probe()
    return (f"Blender MCP server on {mcp_bridge.DEFAULT_HOST}:{mcp_bridge.DEFAULT_PORT}: "
            f"{'DETECTED' if available else 'not running'}. Agent execution mode: "
            "in-process bpy (same API Blender MCP exposes; socket used by external "
            "clients and when running outside Blender).")


def execute_blender_python(context, code="", **_args):
    if not context.scene.muse_agent.allow_code_execution:
        return ("ERROR: Python execution is disabled. Enable 'Allow Python "
                "Execution' in the Muse Agent panel or use structured tools.")
    _ok, output = mcp_bridge.execute_code(
        code, prefer_mcp=context.scene.muse_agent.prefer_mcp)
    return output


# ---------------------------------------------------------------------------
# Registry (OpenAI tool schemas for Muse Spark)
# ---------------------------------------------------------------------------

def _schema(name, description, properties, required=()):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties,
                       "required": list(required)}}}


_STR = {"type": "string"}
_NUM = {"type": "number"}
_INT = {"type": "integer"}
_VEC3 = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}

TOOLS: dict[str, tuple[dict, object]] = {}


def _register(name, description, properties, required, fn):
    TOOLS[name] = (_schema(name, description, properties, required), fn)


_register("get_scene_info", "Scene summary: objects, faces, materials, render engine.", {}, (), get_scene_info)
_register("list_objects", "List every object with type, faces and location.", {}, (), list_objects)
_register("get_object_info", "Details of one object (or the active one).", {"object_name": _STR}, (), get_object_info)
_register("create_primitive", "Create a CUBE/SPHERE/CYLINDER/CONE/TORUS/PLANE/MONKEY.", {"kind": _STR, "size": _NUM, "location": _VEC3, "name": _STR}, (), create_primitive)
_register("transform_object", "Set location / rotation (degrees) / scale of an object.", {"object_name": _STR, "location": _VEC3, "rotation_deg": _VEC3, "scale": _VEC3}, (), transform_object)
_register("delete_object", "Delete an object by name (or active).", {"object_name": _STR}, (), delete_object)
_register("duplicate_object", "Duplicate an object.", {"object_name": _STR}, (), duplicate_object)
_register("add_modifier", "Add a modifier: SUBSURF/BEVEL/MIRROR/ARRAY/SOLIDIFY/DECIMATE/BOOLEAN etc. Extra numeric props (levels, count, ratio, thickness) are applied when given.", {"object_name": _STR, "modifier_type": _STR, "levels": _INT, "count": _INT, "ratio": _NUM}, ("modifier_type",), add_modifier)
_register("apply_modifier", "Apply a modifier (first, or by name).", {"object_name": _STR, "modifier_name": _STR}, (), apply_modifier)
_register("create_material", "Create a Principled material; optionally assign it.", {"name": _STR, "color": _VEC3, "metallic": _NUM, "roughness": _NUM, "assign_to": _STR}, (), create_material)
_register("generate_texture", "Generate a Muse Image 1.0 texture from a prompt and apply it as a material (optionally to a named object).", {"prompt": _STR, "object_name": _STR, "tileable": {"type": "boolean"}}, ("prompt",), generate_texture)
_register("add_gn_texture", "Add the Muse GN Texture Geometry Nodes modifier (texture displacement + muse_height).", {"object_name": _STR, "strength": _NUM, "texture_scale": _NUM}, (), add_gn_texture)
_register("analyze_scene", "Optimization report: heaviest meshes, oversized textures, unused materials.", {}, (), analyze_scene)
_register("optimize_object", "Decimate one mesh to a face ratio (applied).", {"object_name": _STR, "ratio": _NUM}, (), optimize_object)
_register("clean_mesh", "Merge by distance + delete loose geometry on a mesh.", {"object_name": _STR}, (), clean_mesh)
_register("resize_textures", "Downscale every image over max_size px (in Blender data).", {"max_size": _INT}, (), resize_textures)
_register("purge_orphans", "Purge unused materials/images/meshes.", {}, (), purge_orphans)
_register("optimize_scene", "Whole scene: decimate heavy meshes, resize textures, purge orphans. Reports before/after.", {"decimate_ratio": _NUM, "face_threshold": _INT, "texture_max": _INT}, (), optimize_scene)
_register("add_light", "Add AREA/POINT/SUN/SPOT light.", {"light_type": _STR, "location": _VEC3, "energy": _NUM, "name": _STR}, (), add_light)
_register("add_camera", "Add a camera and make it active.", {"location": _VEC3, "name": _STR}, (), add_camera)
_register("set_render_settings", "Set engine (CYCLES / BLENDER_EEVEE_NEXT), resolution, Cycles samples.", {"engine": _STR, "resolution_x": _INT, "resolution_y": _INT, "samples": _INT}, (), set_render_settings)
_register("render_image", "Render the current frame to a PNG path.", {"filepath": _STR}, (), render_image)
_register("save_file", "Save the .blend (compressed).", {"filepath": _STR}, (), save_file)
_register("export_glb", "Export GLB for web (modifiers NOT applied, no Draco).", {"filepath": _STR}, ("filepath",), export_glb)
_register("keyframe_object", "Insert a keyframe (location/rotation_euler/scale).", {"object_name": _STR, "frame": _INT, "data_path": _STR}, (), keyframe_object)
_register("set_frame_range", "Set scene frame range.", {"frame_start": _INT, "frame_end": _INT}, (), set_frame_range)
_register("optimize_for_web", "Product Showcase step 1: create Low/Medium/High LODs of a mesh (<name>_lod_high/_medium/_low, panel ratios; High keeps full detail, original kept). The site exports all three and visitors pick quality.", {"object_name": _STR}, (), optimize_for_web)
_register("bake_product_maps", "Product Showcase step 2: bake Normal + AO from the original onto the Medium + Low LODs (before any render or GLB export; High keeps full geometry).", {"object_name": _STR}, (), bake_product_maps_tool)
_register("create_showcase_animation", "Product Showcase step 3: bake a showcase animation into the product for the website GLB. style: TURNTABLE / TURNTABLE_FLOAT / HERO_REVEAL / ORBIT_REVEAL / FLOAT_SPIN / PULSE / SWING / TILT_ORBIT / DIORAMA_ORBIT / EXPLODE_FLOAT / NONE.", {"object_name": _STR, "style": _STR, "frames": _INT}, (), create_showcase_animation_tool)
_register("seed_cms", "Product Showcase step 4a: seed the in-Blender CMS (en + hi languages, default showcase entries; existing text kept).", {"product_name": _STR}, (), seed_cms_tool)
_register("set_cms_text", "Set one CMS translation, e.g. key=hero_title lang=hi text='...'. Creates the entry/language when missing.", {"key": _STR, "lang": _STR, "text": _STR}, ("key",), set_cms_text_tool)
_register("improve_prompt", "Website Step 0: expand a short product brief into commerce copy + hero/lifestyle/detail image prompts and alt texts (deterministic, offline).", {"brief": _STR, "style": _STR}, (), improve_prompt_tool)
_register("render_catalogue", "Render the e-commerce catalogue in Blender: hero/front/side/back/top/detail JPGs into the website images/ folder.", {}, (), render_catalogue_tool)
_register("build_website", "Build the website for the chosen category (variant: SHOWCASE scroll 3D / SHOPIFY store with gallery+3D+360 and shopify/ import files / CONFIGURATOR 360° per finish via cloudimage-360): improve prompt, bake, LOD GLBs, Blender catalogue + spin renders, CMS site. Returns folder, validation, live URL and serve command.", {"variant": _STR}, (), build_website_tool)
_register("check_site", "Harness: probe whether the showcase site is running on its port and validate the built files. Returns the live URL when up.", {}, (), check_site_tool)
_register("list_skills", "List bundled Blender skills (incl. GitHub skills).", {}, (), list_skills_tool)
_register("get_skill", "Load a skill's full guidance by id (e.g. size-reduction, asset-optimization, blender-lighting).", {"skill_id": _STR}, ("skill_id",), get_skill_tool)
_register("mcp_health", "Check Blender MCP server detection on port 9876 and execution mode.", {}, (), mcp_health)
_register("execute_blender_python", "Run arbitrary Blender Python (bpy) for anything structured tools cannot do. Code runs in Blender; print() results. Requires Allow Python Execution.", {"code": _STR}, ("code",), execute_blender_python)


def tool_schemas() -> list[dict]:
    return [schema for schema, _fn in TOOLS.values()]


def execute_tool(context, name: str, arguments: dict) -> str:
    """Run one tool by name. Main thread only. Never raises."""
    entry = TOOLS.get(name)
    if entry is None:
        return f"ERROR: unknown tool '{name}'. Available: {', '.join(sorted(TOOLS))}"
    _schema_dict, fn = entry
    try:
        result = fn(context, **(arguments or {}))
    except Exception as exc:  # noqa: BLE001 - fed back to the model
        return f"ERROR in {name}: {type(exc).__name__}: {exc}"
    return str(result)[:MAX_RESULT]
