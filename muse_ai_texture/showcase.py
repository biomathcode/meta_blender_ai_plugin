"""Product Showcase core: LODs -> bake -> animate -> CMS -> Three.js website.

Used by the Showcase panel operators and by the Muse agent tools, so the
agent workflow and the buttons run exactly the same code:

  1. create_lods()        — keep three versions of the model instead of
                            crushing one copy: High (cleanup only, full
                            detail), Medium and Low (panel ratios). The
                            site exports all three GLBs and the visitor
                            picks quality Low / Medium / High.
  2. bake_lod_maps()      — bake Normal + AO from the original onto the
                            Medium + Low LODs (High needs none) and wire
                            the maps in, *before* the GLB export.
  3. create_showcase_animation() — bake one of ten scroll-scrubbed
                            variants into the optimized copy; exported
                            in the GLB.
  4. CMS (web_cms.py)     — languages / entries / translations stored in
                            Scene properties; edited in the Showcase panel.
  5. build_website()      — export the optimized copy as product.glb and
                            write a Three.js + GSAP ScrollTrigger site
                            with the CMS baked in (content.json alongside).
                            The site harness validates the export, picks
                            a free port, and records a manifest.
"""

from __future__ import annotations

import json
import math
import os

import bpy

from . import api_client, site_harness, site_prompts, site_template, utils, web_cms


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LOD_LEVELS = ("high", "medium", "low")


def lod_object_name(source_name: str, level: str) -> str:
    return f"{source_name}_lod_{level}"


def lod_ratios(site) -> dict:
    """Level -> face fraction kept, from the panel (sane ordered defaults)."""
    return {
        "high": float(getattr(site, "lod_high_ratio", 1.0) or 1.0),
        "medium": float(getattr(site, "lod_medium_ratio", 0.45) or 0.45),
        "low": float(getattr(site, "lod_low_ratio", 0.12) or 0.12),
    }


def lod_objects(context) -> dict:
    """Level -> LOD object (only levels that exist), high first."""
    site = context.scene.muse_site
    found = {}
    for level in LOD_LEVELS:
        name = getattr(site, f"lod_{level}_object", "") or ""
        obj = bpy.data.objects.get(name) if name else None
        if obj is not None and obj.type == "MESH":
            found[level] = obj
    return found


def product_object(context):
    """Primary showcase mesh: Medium LOD, else optimized copy, else active."""
    site = context.scene.muse_site
    lods = lod_objects(context)
    if "medium" in lods:
        return lods["medium"]
    for name in (site.optimized_object, site.product_object):
        obj = bpy.data.objects.get(name) if name else None
        if obj is not None and obj.type == "MESH":
            return obj
    return utils.active_mesh_object(context)


def _clean_mesh(obj, context) -> None:
    """Merge-by-distance + delete loose, via bmesh (works headless too)."""
    import bmesh

    mesh = bmesh.new()
    mesh.from_mesh(obj.data)
    bmesh.ops.remove_doubles(mesh, verts=list(mesh.verts), dist=0.0001)
    loose_verts = [v for v in mesh.verts if not v.link_faces]
    if loose_verts:
        bmesh.ops.delete(mesh, geom=loose_verts, context="VERTS")
    loose_edges = [e for e in mesh.edges if not e.link_faces]
    if loose_edges:
        bmesh.ops.delete(mesh, geom=loose_edges, context="EDGES")
    mesh.to_mesh(obj.data)
    mesh.free()
    obj.data.update()


def _face_count(obj) -> int:
    return len(obj.data.polygons) if obj and obj.type == "MESH" and obj.data else 0


def _is_manifold(obj) -> bool:
    try:
        import bmesh
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        ok = all(e.is_manifold for e in bm.edges)
        bm.free()
        return ok
    except Exception:  # noqa: BLE001
        return False


def _planar_fraction(obj, threshold_deg: float = 5.0) -> float:
    """Fraction of faces whose neighbours are near-coplanar (CAD-like)."""
    try:
        polys = list(obj.data.polygons)
        if len(polys) < 2:
            return 0.0
        flat = 0
        for poly in polys:
            n = poly.normal
            # Cheap proxy: axis-aligned normals read as manufactured/planar.
            if max(abs(n.x), abs(n.y), abs(n.z)) > 0.985:
                flat += 1
        return flat / max(len(polys), 1)
    except Exception:  # noqa: BLE001
        return 0.0


def _apply_modifier(context, obj, mod) -> bool:
    try:
        override = context.copy()
        override["object"] = obj
        override["active_object"] = obj
        with context.temp_override(**override):
            bpy.ops.object.modifier_apply(modifier=mod.name)
        return True
    except Exception:  # noqa: BLE001 - fall back to keeping the modifier live
        try:
            obj.modifiers.remove(mod)
        except Exception:  # noqa: BLE001
            pass
        return False


# ---------------------------------------------------------------------------
# Step 1 — Optimize (decimate is NOT always the answer)
# ---------------------------------------------------------------------------

def _strategy_decimate(context, obj, ratio: float) -> str:
    if ratio >= 0.999 or _face_count(obj) == 0:
        return "decimate (skipped, ratio 1.0)"
    ratio = max(0.02, min(1.0, float(ratio)))
    mod = obj.modifiers.new("Muse Web Decimate", "DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = ratio
    mod.use_collapse_triangulate = True
    _apply_modifier(context, obj, mod)
    return f"decimate collapse ratio {ratio:.2f}"


def _strategy_limited_dissolve(context, obj, angle_deg: float = 5.0) -> str:
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    faces = list(bm.faces)
    bmesh.ops.dissolve_limit(bm, angle_limit=math.radians(angle_deg),
                             verts=list(bm.verts), edges=list(bm.edges),
                             use_dissolve_boundaries=False)
    # Triangulate only n-gons left by dissolve (quads stay quads; the
    # glTF exporter triangulates at export time anyway).
    ngons = [f for f in bm.faces if len(f.verts) > 4]
    if ngons:
        bmesh.ops.triangulate(bm, faces=ngons)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return f"limited dissolve {angle_deg:.0f}° + triangulate"


def _strategy_voxel(context, obj, voxel_size: float) -> str:
    mesh = obj.data
    mesh.remesh_mode = "VOXEL"
    mesh.remesh_voxel_size = max(0.001, float(voxel_size))
    mesh.remesh_voxel_adaptivity = 0.0
    try:
        override = context.copy()
        override["object"] = obj
        override["active_object"] = obj
        with context.temp_override(**override):
            bpy.ops.object.voxel_remesh()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Voxel remesh failed (needs a manifold mesh): {exc}") from exc
    return f"voxel remesh {voxel_size:.3f}m"


def _strategy_quadriflow(context, obj, target_faces: int, preserve_sharp: bool) -> str:
    try:
        override = context.copy()
        override["object"] = obj
        override["active_object"] = obj
        with context.temp_override(**override):
            bpy.ops.object.quadriflow_remesh(
                mode="FACES", target_faces=int(target_faces),
                use_mesh_symmetry=False,
                use_preserve_sharp=bool(preserve_sharp),
                use_preserve_boundary=bool(preserve_sharp),
                smooth_normals=True, seed=0)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"QuadriFlow failed (needs a manifold mesh — try Voxel first): {exc}") from exc
    return f"quadriflow retopo → {target_faces} target faces"


def _pick_smart_strategy(obj, ratio: float) -> tuple[str, str]:
    """Return (strategy, reason) for SMART mode."""
    faces = _face_count(obj)
    if faces == 0:
        return "DECIMATE", "empty mesh"
    planar = _planar_fraction(obj)
    if planar > 0.45:
        return "LIMITED_DISSOLVE", f"{planar:.0%} near-planar faces (hard-surface/CAD)"
    if faces > 60000 and _is_manifold(obj):
        return "QUADRIFLOW", f"{faces} faces, manifold — clean quads beat collapsed tris"
    if faces > 60000:
        return "VOXEL", f"{faces} faces, non-manifold — voxel cleanup then reduce"
    if faces > 8000:
        return "DECIMATE", f"{faces} faces, organic/mid-poly — decimate + bake is fastest"
    return "LIMITED_DISSOLVE", f"only {faces} faces — dissolve cleans without losing the silhouette"


def create_lods(context, obj=None, clean_first: bool = True) -> dict:
    """Create Low / Medium / High LODs of `obj`. Original kept untouched.

    Instead of crushing one web copy, three versions are kept: High is
    cleanup-only at ratio 1.0 (full detail), Medium and Low decimate to
    their panel ratios. The showcase exports all three and the visitor
    picks quality (Low / Medium / High) on the site. Re-running replaces
    the previous LOD objects.
    """
    site = context.scene.muse_site
    if obj is None:
        named = bpy.data.objects.get(site.product_object) if site.product_object else None
        obj = named if (named is not None and named.type == "MESH") \
            else utils.active_mesh_object(context)
    if obj is None or obj.type != "MESH":
        raise RuntimeError("Select a mesh object to create LODs from first.")
    # Never LOD an LOD: strip a tier suffix back to the source name.
    source = obj
    before = _face_count(source)
    ratios = lod_ratios(site)
    lods: dict = {}
    for level in LOD_LEVELS:
        name = lod_object_name(source.name, level)
        old = bpy.data.objects.get(name)
        if old is not None and old != source:
            bpy.data.objects.remove(old, do_unlink=True)
        copy = source.copy()
        copy.data = source.data.copy()
        copy.name = name
        if copy.animation_data:
            copy.animation_data_clear()
        context.collection.objects.link(copy)
        if clean_first:
            _clean_mesh(copy, context)
        ratio = ratios[level]
        detail = "cleanup only (full detail)" if ratio >= 0.999 else \
            _strategy_decimate(context, copy, ratio)
        if not copy.data.uv_layers:
            utils.ensure_uv_map(copy)
        faces = _face_count(copy)
        setattr(site, f"lod_{level}_object", copy.name)
        setattr(site, f"lod_faces_{level}", faces)
        lods[level] = {"object": copy.name, "faces": faces,
                       "ratio": ratio, "detail": detail}
    site.faces_before = before
    site.faces_after = lods["medium"]["faces"]
    site.optimized_object = lods["medium"]["object"]  # compat: primary copy
    site.product_object = source.name
    return {"source": source.name, "faces_before": before, "lods": lods}


def optimize_product(context, obj=None, ratio: float = 0.35,
                     clean_first: bool = True, strategy: str | None = None) -> dict:
    """Back-compat wrapper: now creates the three LODs (see create_lods).

    Returns the Medium tier in the old single-copy keys, plus `lods`.
    `ratio`/`strategy` are accepted for old agent calls and ignored —
    tier ratios live in the panel (lod_high/medium/low_ratio).
    """
    result = create_lods(context, obj=obj, clean_first=clean_first)
    medium = result["lods"]["medium"]
    return {"object": medium["object"], "source": result["source"],
            "strategy": "LOD",
            "detail": "; ".join(
                f"{level} {info['faces']} faces ({info['detail']})"
                for level, info in result["lods"].items()),
            "reason": "", "faces_before": result["faces_before"],
            "faces_after": medium["faces"], "lods": result["lods"]}


# ---------------------------------------------------------------------------
# Step 2 — Bake high-poly detail onto the web copy (before render / GLB)
# ---------------------------------------------------------------------------

def _combined_albedo(obj, ao_img, base_image, base_rgba):
    """Return a new image with pixels = base * AO (or None without numpy)."""
    try:
        import numpy as np
    except ImportError:
        return None
    res = int(ao_img.size[0])
    if res <= 0:
        return None
    ao = np.empty(res * res * 4, dtype=np.float32)
    ao_img.pixels.foreach_get(ao)
    ao = ao.reshape(res, res, 4)
    if base_image is not None:
        tmp = base_image.copy()
        tmp.name = f"{obj.name}_albedo_src"
        if tmp.size[0] != res or tmp.size[1] != res:
            tmp.scale(res, res)
        base = np.empty(res * res * 4, dtype=np.float32)
        tmp.pixels.foreach_get(base)
        base = base.reshape(res, res, 4)
        rgb = base[:, :, :3] * ao[:, :, :3]
        bpy.data.images.remove(tmp)
    else:
        rgb = ao[:, :, :3] * np.array(base_rgba[:3], dtype=np.float32)
    out = bpy.data.images.get(f"{obj.name}_albedo")
    if out is not None:
        bpy.data.images.remove(out)
    out = bpy.data.images.new(f"{obj.name}_albedo", width=res, height=res, alpha=False)
    flat = np.ones(res * res * 4, dtype=np.float32)
    flat_rgb = flat.reshape(res, res, 4)
    flat_rgb[:, :, :3] = rgb
    out.pixels.foreach_set(flat)
    out.update()
    try:
        out.pack()
    except RuntimeError:
        pass
    return out


def _ensure_bake_material(obj, normal_img, ao_img) -> None:
    """Wire baked maps into a Principled material on `obj`."""
    mat = obj.data.materials[0] if obj.data.materials else None
    if mat is None:
        mat = bpy.data.materials.new(f"{obj.name}_baked")
        obj.data.materials.append(mat)
    mat.use_nodes = True
    tree = mat.node_tree
    principled = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if principled is None:
        return
    texcoord = next((n for n in tree.nodes if n.type == "TEX_COORD"), None)
    if texcoord is None:
        texcoord = tree.nodes.new("ShaderNodeTexCoord")
        texcoord.location = (-900, 0)
    if normal_img is not None:
        tex = tree.nodes.new("ShaderNodeTexImage")
        tex.label = "Baked Normal"
        tex.image = normal_img
        tex.image.colorspace_settings.name = "Non-Color"
        tex.location = (-650, -260)
        tree.links.new(texcoord.outputs["UV"], tex.inputs["Vector"])
        nrm = tree.nodes.new("ShaderNodeNormalMap")
        nrm.location = (-380, -260)
        tree.links.new(tex.outputs["Color"], nrm.inputs["Color"])
        if "Normal" in principled.inputs:
            # Replace any existing normal input.
            for link in list(principled.inputs["Normal"].links):
                tree.links.remove(link)
            tree.links.new(nrm.outputs["Normal"], principled.inputs["Normal"])
    if ao_img is not None:
        # Ship AO pre-multiplied into the albedo. The Blender glTF
        # exporter does not reliably split a Mix(BaseColor, AO) node
        # into baseColorTexture + occlusionTexture (with a flat colour
        # it shipped the AO as the base colour — grey product), so we
        # multiply the pixels once here: albedo = base * AO. Three.js
        # then needs no occlusion support to show the baked shading.
        base_links = list(principled.inputs["Base Color"].links)
        base_image = None
        base_node = base_links[0].from_node if base_links else None
        if base_node is not None and base_node.type == "TEX_IMAGE":
            base_image = base_node.image
        base_rgba = tuple(principled.inputs["Base Color"].default_value)
        combined = _combined_albedo(obj, ao_img, base_image, base_rgba)
        if combined is not None:
            for link in base_links:
                tree.links.remove(link)
            tex = tree.nodes.new("ShaderNodeTexImage")
            tex.label = "Baked Albedo (base × AO)"
            tex.image = combined
            tex.image.colorspace_settings.name = "sRGB"
            tex.location = (-650, 80)
            tree.links.new(texcoord.outputs["UV"], tex.inputs["Vector"])
            if "Base Color" in principled.inputs:
                tree.links.new(tex.outputs["Color"], principled.inputs["Base Color"])
        else:
            # No numpy: fall back to the Mix node (correct in Blender,
            # best-effort in glTF).
            tex = tree.nodes.new("ShaderNodeTexImage")
            tex.label = "Baked AO"
            tex.image = ao_img
            tex.image.colorspace_settings.name = "Non-Color"
            tex.location = (-650, -520)
            tree.links.new(texcoord.outputs["UV"], tex.inputs["Vector"])
            mix = tree.nodes.new("ShaderNodeMixRGB")
            mix.blend_type = "MULTIPLY"
            mix.inputs[0].default_value = 1.0
            mix.location = (-120, 120)
            if base_links:
                src = base_links[0].from_socket
                tree.links.remove(base_links[0])
                tree.links.new(src, mix.inputs[1])
            else:
                mix.inputs[1].default_value = base_rgba
            tree.links.new(tex.outputs["Color"], mix.inputs[2])
            if "Base Color" in principled.inputs:
                tree.links.new(mix.outputs["Color"], principled.inputs["Base Color"])


def bake_product_maps(context, high_obj=None, low_obj=None) -> dict:
    """Bake Normal + AO from the high-poly original onto the web copy.

    Must run *before* rendering the product or exporting the GLB — the
    baked maps are what let the low-poly copy keep the high-poly look.
    Uses Cycles Selected-to-Active baking; restores engine/settings.
    """
    site = context.scene.muse_site
    low_obj = low_obj or product_object(context)
    if low_obj is None or low_obj.type != "MESH":
        raise RuntimeError("Optimize a mesh first, then bake.")
    if high_obj is None and site.product_object:
        high_obj = bpy.data.objects.get(site.product_object)
    if high_obj is None or high_obj == low_obj:
        # Single-mesh bake (AO/self-detail only) is still useful.
        high_obj = low_obj
    res = int(getattr(site, "bake_resolution", "1024"))
    margin = int(getattr(site, "bake_margin", 16))
    cage = float(getattr(site, "bake_cage_extrusion", 0.02))
    want_normal = bool(getattr(site, "bake_normal", True))
    want_ao = bool(getattr(site, "bake_ao", True))
    if not want_normal and not want_ao:
        return {"object": low_obj.name, "baked": [], "detail": "both maps disabled"}

    utils.ensure_uv_map(low_obj)
    scene = context.scene
    prev_engine = scene.render.engine
    prev_device = getattr(scene.cycles, "device", "CPU") if hasattr(scene, "cycles") else "CPU"
    baked: list[str] = []
    images: dict[str, object] = {}
    try:
        scene.render.engine = "CYCLES"
        try:
            scene.cycles.device = "CPU"  # deterministic in background/batch
            scene.cycles.samples = 16
            scene.cycles.bake_type = "NORMAL"
        except Exception:  # noqa: BLE001
            pass
        bake = scene.render.bake
        bake.use_selected_to_active = high_obj != low_obj
        bake.use_cage = False
        bake.cage_extrusion = cage
        bake.margin = margin
        bake.normal_space = "TANGENT"

        # Material + image nodes must exist and be *active* for baking.
        if not low_obj.data.materials:
            low_obj.data.materials.append(bpy.data.materials.new(f"{low_obj.name}_baked"))
        mat = low_obj.data.materials[0]
        mat.use_nodes = True

        def _bake_one(kind: str, bake_type: str):
            img_name = f"{low_obj.name}_{kind}"
            img = bpy.data.images.get(img_name) or bpy.data.images.new(
                img_name, width=res, height=res, alpha=False, float_buffer=False)
            if img.size[0] != res or img.size[1] != res:
                img.scale(res, res)
            img.colorspace_settings.name = "Non-Color"
            node = mat.node_tree.nodes.new("ShaderNodeTexImage")
            node.image = img
            node.select = True
            mat.node_tree.nodes.active = node
            scene.cycles.bake_type = bake_type
            if bake_type == "AO":
                bake.use_pass_direct = False
                bake.use_pass_indirect = False
            # Select high (source) + low (active) for Selected-to-Active.
            for other in context.selected_objects:
                other.select_set(False)
            if high_obj != low_obj:
                high_obj.select_set(True)
            low_obj.select_set(True)
            context.view_layer.objects.active = low_obj
            override = context.copy()
            override["object"] = low_obj
            override["active_object"] = low_obj
            override["selected_objects"] = [o for o in (high_obj, low_obj) if o]
            override["selected_editable_objects"] = [low_obj]
            with context.temp_override(**override):
                bpy.ops.object.bake(type=bake_type)
            mat.node_tree.nodes.remove(node)
            try:
                img.pack()
            except RuntimeError:
                pass
            return img

        if want_normal:
            images["normal"] = _bake_one("normal", "NORMAL")
            baked.append(f"normal {res}px")
        if want_ao:
            images["ao"] = _bake_one("ao", "AO")
            baked.append(f"AO {res}px")
    except Exception as exc:  # noqa: BLE001 - bake is best-effort, never block export
        site.bake_status = f"Bake skipped: {exc}"
        return {"object": low_obj.name, "baked": [], "detail": f"skipped: {exc}"}
    finally:
        try:
            scene.render.engine = prev_engine
            if hasattr(scene, "cycles"):
                scene.cycles.device = prev_device
        except Exception:  # noqa: BLE001
            pass

    _ensure_bake_material(low_obj, images.get("normal"), images.get("ao"))
    site.bake_status = f"Baked {', '.join(baked)} from {high_obj.name} → {low_obj.name} ({res}px, margin {margin}px)."
    return {"object": low_obj.name, "source": high_obj.name,
            "baked": baked, "resolution": res,
            "detail": site.bake_status}


def bake_lod_maps(context) -> dict:
    """Bake source detail onto Medium + Low LODs (High keeps full detail)."""
    site = context.scene.muse_site
    lods = lod_objects(context)
    if not lods:
        raise RuntimeError("Create LODs first, then bake.")
    source = bpy.data.objects.get(site.product_object) if site.product_object else None
    results = {}
    for level in ("medium", "low"):
        target = lods.get(level)
        if target is None:
            continue
        results[level] = bake_product_maps(
            context, high_obj=source, low_obj=target)
    site.bake_status = "; ".join(
        f"{level}: {r.get('detail', '')}" for level, r in results.items())
    return {"lods": results, "detail": site.bake_status}


# ---------------------------------------------------------------------------
# Step 3 — Showcase animation (baked, exported in the GLB)
# ---------------------------------------------------------------------------

def _fcurves(action):
    curves = []
    try:
        curves = list(action.fcurves)
        if curves:
            return curves
    except Exception:  # noqa: BLE001 - Blender 4.4+/5.x layered actions
        pass
    try:
        for layer in action.layers:
            for strip in layer.strips:
                bag = getattr(strip, "channelbag", None)
                bag = bag() if callable(bag) else bag
                if bag is not None:
                    curves.extend(bag.fcurves)
    except Exception:  # noqa: BLE001
        pass
    return curves


def _set_interpolation(action, mode: str, only_path: str = "") -> None:
    for curve in _fcurves(action):
        if only_path and curve.data_path != only_path:
            continue
        for point in curve.keyframe_points:
            point.interpolation = mode


_ANIMATION_NAMES = {
    "TURNTABLE": "ShowcaseTurntable",
    "TURNTABLE_FLOAT": "ShowcaseTurntableFloat",
    "HERO_REVEAL": "ShowcaseHeroReveal",
    "ORBIT_REVEAL": "ShowcaseOrbitReveal",
    "FLOAT_SPIN": "ShowcaseFloatSpin",
    "PULSE": "ShowcasePulse",
    "SWING": "ShowcaseSwing",
    "TILT_ORBIT": "ShowcaseTiltOrbit",
    "DIORAMA_ORBIT": "ShowcaseDioramaOrbit",
    "EXPLODE_FLOAT": "ShowcaseExplodeFloat",
    "DROP_BOUNCE": "ShowcaseDropBounce",
    "TUMBLE_360": "ShowcaseTumble360",
    "ELEVATE_REVEAL": "ShowcaseElevateReveal",
}


def create_showcase_animation(context, obj=None, style: str = "TURNTABLE",
                              frames: int = 120) -> dict:
    obj = obj or product_object(context)
    if obj is None or obj.type != "MESH":
        raise RuntimeError("Optimize (or select) a mesh first, then add animation.")
    style = (style or "TURNTABLE").upper()
    if style == "NONE":
        return {"object": obj.name, "animation": "none", "frames": 0}
    if style not in _ANIMATION_NAMES:
        style = "TURNTABLE"
    scene = context.scene
    frames = max(12, int(frames))
    start, end = 1, 1 + frames
    scene.frame_start, scene.frame_end = start, end
    mid = start + frames // 2
    quarter = start + frames // 4
    three_quarter = start + (3 * frames) // 4

    if obj.animation_data:
        obj.animation_data_clear()
    base_loc = tuple(obj.location)
    base_scale = tuple(obj.scale) if obj.scale else (1.0, 1.0, 1.0)
    obj.rotation_euler = (0.0, 0.0, 0.0)
    obj.scale = base_scale

    def key(path, frame, index=None):
        if index is None:
            obj.keyframe_insert(data_path=path, frame=frame)
        else:
            obj.keyframe_insert(data_path=path, index=index, frame=frame)

    def spin_z(a0, a1, f0=start, f1=end):
        obj.rotation_euler.z = a0
        key("rotation_euler", f0, 2)
        obj.rotation_euler.z = a1
        key("rotation_euler", f1, 2)

    def float_z(amp, f0=start, fm=mid, f1=end):
        obj.location.z = base_loc[2]
        key("location", f0, 2)
        obj.location.z = base_loc[2] + amp
        key("location", fm, 2)
        obj.location.z = base_loc[2]
        key("location", f1, 2)

    def scale_keys(s0, s1, sm=None):
        for frame, s in ((start, s0), (end, s1)) + (((mid, sm),) if sm is not None else ()):
            obj.scale = (base_scale[0] * s, base_scale[1] * s, base_scale[2] * s)
            key("scale", frame)

    if style == "TURNTABLE":
        spin_z(0.0, math.tau)
    elif style == "TURNTABLE_FLOAT":
        spin_z(0.0, math.tau)
        float_z(0.15)
    elif style == "HERO_REVEAL":
        # Half-spin with a scale-up entrance; Bezier/BACK applied below.
        spin_z(-math.pi * 0.5, math.pi * 0.5)
        scale_keys(0.82, 1.0)
        float_z(0.06)
    elif style == "ORBIT_REVEAL":
        spin_z(0.0, math.tau * 0.75)
        obj.location.z = base_loc[2] - 0.12
        key("location", start, 2)
        obj.location.z = base_loc[2] + 0.08
        key("location", mid, 2)
        obj.location.z = base_loc[2]
        key("location", end, 2)
        scale_keys(0.88, 1.0)
    elif style == "FLOAT_SPIN":
        spin_z(0.0, math.tau)
        float_z(0.18)
    elif style == "PULSE":
        spin_z(0.0, math.tau)
        for frame, s in ((start, 1.0), (quarter, 1.07), (mid, 1.0),
                         (three_quarter, 1.07), (end, 1.0)):
            obj.scale = (base_scale[0] * s, base_scale[1] * s, base_scale[2] * s)
            key("scale", frame)
    elif style == "SWING":
        amp = math.radians(14)
        for frame, ax, az in ((start, amp, 0.0), (quarter, 0.0, amp * 0.5),
                              (mid, -amp, 0.0), (three_quarter, 0.0, -amp * 0.5),
                              (end, amp, 0.0)):
            obj.rotation_euler.x, obj.rotation_euler.z = ax, az
            key("rotation_euler", frame, 0)
            key("rotation_euler", frame, 2)
        float_z(0.05)
    elif style == "TILT_ORBIT":
        obj.rotation_euler.x = math.radians(12)
        key("rotation_euler", start, 0)
        obj.rotation_euler.x = math.radians(12)
        key("rotation_euler", end, 0)
        spin_z(0.0, math.tau)
    elif style == "DIORAMA_ORBIT":
        iso = math.radians(35.264)  # isometric tilt
        obj.rotation_euler.x = iso
        key("rotation_euler", start, 0)
        obj.rotation_euler.x = iso
        key("rotation_euler", end, 0)
        spin_z(0.0, math.tau)
        float_z(0.08)
    elif style == "EXPLODE_FLOAT":
        spin_z(0.0, math.tau * 0.5)
        float_z(0.22)
        for frame, s in ((start, 1.0), (mid, 1.05), (end, 1.0)):
            obj.scale = (base_scale[0] * s, base_scale[1] * s, base_scale[2] * s)
            key("scale", frame)
    elif style == "DROP_BOUNCE":
        # Animated entrance: start above, drop to rest (BOUNCE ease below).
        obj.location.z = base_loc[2] + 1.1
        key("location", start, 2)
        obj.location.z = base_loc[2]
        key("location", mid, 2)
        obj.location.z = base_loc[2]
        key("location", end, 2)
        spin_z(-0.35, 0.0, start, mid)
    elif style == "TUMBLE_360":
        obj.rotation_euler.x = 0.0
        key("rotation_euler", start, 0)
        obj.rotation_euler.x = math.tau
        key("rotation_euler", end, 0)
        spin_z(0.0, math.pi)
    elif style == "ELEVATE_REVEAL":
        obj.location.z = base_loc[2] - 0.45
        key("location", start, 2)
        obj.location.z = base_loc[2]
        key("location", end, 2)
        spin_z(-math.pi * 0.75, 0.0)
        scale_keys(0.85, 1.0)

    # Reset to the first frame pose.
    obj.location = base_loc
    obj.scale = base_scale
    if style not in ("TILT_ORBIT", "DIORAMA_ORBIT"):
        obj.rotation_euler.x = 0.0

    if obj.animation_data and obj.animation_data.action:
        action = obj.animation_data.action
        # Turntables scrubbed by scroll must be even (Linear); reveals want ease.
        if style in ("TURNTABLE", "TURNTABLE_FLOAT", "FLOAT_SPIN", "PULSE",
                     "TILT_ORBIT", "DIORAMA_ORBIT", "EXPLODE_FLOAT", "TUMBLE_360"):
            _set_interpolation(action, "LINEAR")
        elif style == "DROP_BOUNCE":
            _set_interpolation(action, "LINEAR")
            for curve in _fcurves(action):
                if curve.data_path == "location":
                    for point in curve.keyframe_points:
                        point.interpolation = "BOUNCE"
                        point.easing = "EASE_OUT"
        elif style == "ELEVATE_REVEAL":
            _set_interpolation(action, "BEZIER")
            for curve in _fcurves(action):
                if curve.data_path == "scale":
                    for point in curve.keyframe_points:
                        point.interpolation = "BACK"
                        point.easing = "EASE_OUT"
        elif style in ("HERO_REVEAL", "ORBIT_REVEAL"):
            _set_interpolation(action, "BEZIER")
            # BACK ease on the scale reveal gives the overshoot settle.
            for curve in _fcurves(action):
                if curve.data_path == "scale":
                    for point in curve.keyframe_points:
                        point.interpolation = "BACK"
                        point.easing = "EASE_OUT"
        elif style == "SWING":
            _set_interpolation(action, "SINE")
        # Avoid a ".001" suffix when a stale showcase action owns the name.
        stale = bpy.data.actions.get(_ANIMATION_NAMES[style])
        if stale is not None and stale != action:
            try:
                bpy.data.actions.remove(stale)
            except Exception:  # noqa: BLE001
                pass
        action.name = _ANIMATION_NAMES[style]
        # Share the same action with the other LODs (identical transforms),
        # so every exported tier carries the showcase animation.
        for other in lod_objects(context).values():
            if other == obj:
                continue
            if other.animation_data:
                other.animation_data_clear()
            other.animation_data_create().action = action
    scene.frame_set(start)
    return {"object": obj.name,
            "animation": obj.animation_data.action.name
            if obj.animation_data and obj.animation_data.action else _ANIMATION_NAMES[style],
            "style": style, "frames": frames}


# ---------------------------------------------------------------------------
# Step 4 — CMS <-> plain dicts
# ---------------------------------------------------------------------------

def cms_languages(context) -> list[dict]:
    return [{"code": lang.code, "label": lang.label, "is_default": lang.is_default}
            for lang in context.scene.muse_site_languages]


def cms_entries(context) -> list[dict]:
    return [{"key": entry.key, "section": entry.section,
             "translations": {t.lang: t.text for t in entry.translations}}
            for entry in context.scene.muse_site_entries]


def seed_cms(context, product_name: str = "") -> dict:
    """Seed default languages + entries (existing user text is preserved)."""
    scene = context.scene
    if not scene.muse_site_languages:
        for lang in web_cms.seed_languages():
            item = scene.muse_site_languages.add()
            item.code, item.label, item.is_default = (
                lang["code"], lang["label"], lang["is_default"])
    existing = {entry.key: entry for entry in scene.muse_site_entries}
    added = 0
    for seed in web_cms.seed_entries(product_name):
        entry = existing.get(seed["key"])
        if entry is None:
            entry = scene.muse_site_entries.add()
            entry.key, entry.section = seed["key"], seed["section"]
            added += 1
        have = {t.lang for t in entry.translations}
        for code, text in seed["translations"].items():
            if code not in have and text:
                item = entry.translations.add()
                item.lang, item.text = code, text
    return {"languages": len(scene.muse_site_languages),
            "entries": len(scene.muse_site_entries), "added": added}


def set_cms_text(context, key: str, lang: str, text: str) -> str:
    scene = context.scene
    entry = next((e for e in scene.muse_site_entries if e.key == key), None)
    if entry is None:
        entry = scene.muse_site_entries.add()
        entry.key, entry.section = key, "Custom"
    item = next((t for t in entry.translations if t.lang == lang), None)
    if item is None:
        item = entry.translations.add()
        item.lang = lang
    item.text = text
    if not any(l.code == lang for l in scene.muse_site_languages):
        new_lang = scene.muse_site_languages.add()
        new_lang.code, new_lang.label = lang, lang
    return f"CMS {key} [{lang}] = {text[:60]!r}"


def ensure_translation_slots(context) -> None:
    """Give every entry an (editable) slot for every language."""
    codes = [lang.code for lang in context.scene.muse_site_languages]
    for entry in context.scene.muse_site_entries:
        have = {t.lang for t in entry.translations}
        for code in codes:
            if code not in have:
                item = entry.translations.add()
                item.lang, item.text = code, ""


# ---------------------------------------------------------------------------
# Step 0 — Prompt improvement (deterministic; agent can overwrite in CMS)
# ---------------------------------------------------------------------------

def improve_site_prompt(context) -> dict:
    """Expand the user's brief into commerce copy + image-asset prompts."""
    site = context.scene.muse_site
    obj = product_object(context)
    name = site.brand_name or site.product_object or (obj.name if obj else "")
    result = site_prompts.improve_prompt(
        site.prompt_raw, product_name=name,
        style=getattr(site, "prompt_style", "ECOMMERCE"),
        audience=getattr(site, "prompt_audience", ""))
    site.prompt_improved = result["improved"]
    # Seed CMS hero/story copy only where the user has not typed their own
    # non-seed text: improvement must never silently destroy editing work.
    # (Seed defaults are recognisable by the seeded hero prefix.)
    site.prompt_status = (
        f"Improved prompt ready ({result['style']}): hero/lifestyle/detail "
        "image prompts + alt texts generated. Build Website embeds them; "
        "edit freely in the CMS or the Improved Prompt field.")
    return result


# ---------------------------------------------------------------------------
# Step 3b — Blender catalogue + 360 renders (the e-commerce photo set)
# ---------------------------------------------------------------------------

def _product_frame(obj):
    """(centre Vector, radius) framing the product for catalogue cameras."""
    import mathutils
    corners = [obj.matrix_world @ mathutils.Vector(corner)
               for corner in obj.bound_box] if obj.bound_box else [obj.location]
    centre = sum(corners, mathutils.Vector((0, 0, 0))) / max(len(corners), 1)
    radius = max((corner - centre).length for corner in corners) or 1.0
    return centre, max(radius, 0.05)


def _apply_finish(obj, finish: str):
    """Tint Principled base colours for `finish`. Returns restore list."""
    color = site_prompts.finish_color(finish)
    if color is None:
        return []
    saved = []
    for slot in obj.data.materials if obj.type == "MESH" else []:
        mat = slot
        if mat is None or not mat.use_nodes:
            continue
        node = next((n for n in mat.node_tree.nodes
                     if n.type == "BSDF_PRINCIPLED"), None)
        if node is None or "Base Color" not in node.inputs:
            continue
        inp = node.inputs["Base Color"]
        if inp.links:
            continue  # textured material: tint would be invisible/wrong
        saved.append((inp, tuple(inp.default_value)))
        inp.default_value = (color[0], color[1], color[2], 1.0)
    return saved


def _restore_finish(saved) -> None:
    for inp, value in saved:
        try:
            inp.default_value = value
        except Exception:  # noqa: BLE001
            pass


def _render_stills(context, obj, shots: list[tuple[str, float, float, float]],
                   out_files: list[str]) -> list[str]:
    """Render `obj` from (azimuth°, elevation°, dist-mult) shots to files.

    Temporary camera + studio lights, EEVEE, everything restored after —
    the user's scene, camera and render settings are untouched on exit.
    """
    import mathutils
    scene = context.scene
    centre, radius = _product_frame(obj)
    res = int(getattr(context.scene.muse_site, "image_resolution", "1024"))
    saved = {"camera": scene.camera, "engine": scene.render.engine,
             "filepath": scene.render.filepath,
             "res_x": scene.render.resolution_x,
             "res_y": scene.render.resolution_y,
             "fmt": scene.render.image_settings.file_format,
             "quality": scene.render.image_settings.quality,
             "film_transparent": scene.render.film_transparent,
             "hidden": [(o, o.hide_render) for o in scene.objects]}
    cam_data = bpy.data.cameras.new("Muse Catalogue Camera")
    cam = bpy.data.objects.new("Muse Catalogue Camera", cam_data)
    scene.collection.objects.link(cam)
    temps = [cam]
    try:
        if not any(o.type == "LIGHT" for o in scene.objects if not o.hide_render):
            for name, energy, loc, size in (
                    ("Muse Key", 900.0, (3.5, -3.5, 4.5), 3.0),
                    ("Muse Fill", 350.0, (-4.0, -1.5, 2.0), 4.0),
                    ("Muse Rim", 500.0, (0.5, 4.0, 3.0), 2.0)):
                data = bpy.data.lights.new(name, "AREA")
                data.energy, data.shape, data.size = energy, "DISK", size
                light = bpy.data.objects.new(name, data)
                light.location = centre + mathutils.Vector(loc)
                scene.collection.objects.link(light)
                temps.append(light)
        for other in scene.objects:
            other.hide_render = other != obj and other not in temps
        scene.camera = cam
        if bpy.app.background:
            # Headless has no GPU/Metal device (EEVEE aborts); Cycles CPU is
            # deterministic in background/batch, same as the bake path.
            scene.render.engine = "CYCLES"
            try:
                scene.cycles.device = "CPU"
                scene.cycles.samples = 16
            except Exception:  # noqa: BLE001
                pass
        else:
            try:
                scene.render.engine = "BLENDER_EEVEE_NEXT"
            except Exception:  # noqa: BLE001 - older/newer engine ids
                pass
        scene.render.resolution_x = scene.render.resolution_y = res
        scene.render.image_settings.file_format = "JPEG"
        scene.render.image_settings.quality = 90
        scene.render.film_transparent = False
        written = []
        for (azimuth, elevation, dist_mult), filepath in zip(shots, out_files):
            az, el = math.radians(azimuth), math.radians(elevation)
            dist = radius * dist_mult
            cam.location = centre + mathutils.Vector((
                dist * math.cos(el) * math.sin(az),
                -dist * math.cos(el) * math.cos(az),
                dist * math.sin(el)))
            direction = centre - cam.location
            cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
            scene.render.filepath = filepath
            bpy.ops.render.render(write_still=True)
            if os.path.exists(filepath):
                written.append(filepath)
        return written
    finally:
        for temp in temps:
            try:
                bpy.data.objects.remove(temp, do_unlink=True)
            except Exception:  # noqa: BLE001
                pass
        try:
            bpy.data.cameras.remove(cam_data)
        except Exception:  # noqa: BLE001
            pass
        scene.camera = saved["camera"]
        scene.render.engine = saved["engine"]
        scene.render.filepath = saved["filepath"]
        scene.render.resolution_x = saved["res_x"]
        scene.render.resolution_y = saved["res_y"]
        scene.render.image_settings.file_format = saved["fmt"]
        scene.render.image_settings.quality = saved["quality"]
        scene.render.film_transparent = saved["film_transparent"]
        for other, hidden in saved["hidden"]:
            try:
                other.hide_render = hidden
            except Exception:  # noqa: BLE001
                pass


def render_catalogue_images(context, out_dir: str, obj=None) -> list[dict]:
    """Hero/front/side/back/top/detail JPGs — the e-commerce catalogue."""
    obj = obj or product_object(context)
    if obj is None:
        return []
    views = site_prompts.catalogue_views()
    shots = [(v["azimuth"], v["elevation"], v["distance"]) for v in views]
    files = [os.path.join(out_dir, v["file"]) for v in views]
    for path in files:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    written = set(_render_stills(context, obj, shots, files))
    name = context.scene.muse_site.brand_name or obj.name
    return [{**view, "alt": f"{name} — {view['label'].lower()}"}
            for view, path in zip(views, files) if path in written]


def render_spin_images(context, out_dir: str, obj=None,
                       finishes: list[str] | None = None) -> list[dict]:
    """360° frame folders (cloudimage-360) — one spin per finish."""
    site = context.scene.muse_site
    obj = obj or product_object(context)
    if obj is None:
        return []
    finishes = finishes if finishes is not None else \
        site_prompts.parse_finishes(site.finish_options)
    frames = int(site.spin_frames)
    plans = []
    for finish in finishes:
        plan = site_prompts.spin_plan(finish, frames)
        folder = os.path.join(out_dir, plan["folder"])
        os.makedirs(folder, exist_ok=True)
        shots = [(i * 360.0 / frames, 15.0, 2.6) for i in range(frames)]
        # cloudimage {index} is 1-based: frame-1.jpg .. frame-N.jpg
        files = [os.path.join(folder, f"frame-{i + 1}.jpg")
                 for i in range(frames)]
        saved = _apply_finish(obj, finish)
        try:
            _render_stills(context, obj, shots, files)
        finally:
            _restore_finish(saved)
        if all(os.path.exists(path) for path in files):
            plans.append(plan)
    return plans


def generate_ai_image_assets(context, out_dir: str, improved: dict) -> list[dict]:
    """Optional Muse Image stills from the improved prompts (hero/detail)."""
    key, _source, base_url, _model = utils.api_settings(context)
    if not key:
        return []
    made = []
    for kind in ("hero", "lifestyle", "detail"):
        prompt = (improved.get("image_prompts") or {}).get(kind, "")
        if not prompt:
            continue
        try:
            result = api_client.generate_image(
                prompt, key, size="1024x1024", base_url=base_url,
                model="muse-image-1.0", timeout=180)
        except Exception:  # noqa: BLE001 - AI assets never block the build
            continue
        path = os.path.join(out_dir, "images", f"ai_{kind}.{result.image_format}")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(result.image_bytes)
        made.append({"id": f"ai_{kind}", "label": f"AI {kind} (Muse Image)",
                     "file": f"images/ai_{kind}.{result.image_format}",
                     "alt": f"AI-generated {kind} view"})
    return made


# ---------------------------------------------------------------------------
# Step 5 — Build the website (harness-validated)
# ---------------------------------------------------------------------------

def website_dir(context) -> str:
    site = context.scene.muse_site
    if site.export_dir:
        path = bpy.path.abspath(site.export_dir)
    elif bpy.data.filepath:
        path = os.path.join(os.path.dirname(bpy.path.abspath(bpy.data.filepath)),
                            "muse_website")
    else:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "muse_website")
    os.makedirs(path, exist_ok=True)
    return path


def _accent_hex(site) -> str:
    r, g, b = (max(0.0, min(1.0, float(c))) for c in site.accent_color)
    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"


def build_website(context, obj=None, bake_first: bool | None = None) -> dict:
    scene = context.scene
    site = scene.muse_site
    obj = obj or product_object(context)
    if obj is None or obj.type != "MESH":
        raise RuntimeError("Nothing to showcase: optimize or select a mesh first.")
    if not scene.muse_site_entries:
        seed_cms(context, site.brand_name or site.product_object
                 or obj.name.removesuffix("_web"))
    ensure_translation_slots(context)

    # Bake BEFORE the GLB export/render — maps must be in the material
    # that glTF exports, not added afterwards. Medium + Low get baked
    # detail; High already carries the full geometry.
    bake_result = None
    do_bake = bool(getattr(site, "bake_enabled", True)) if bake_first is None else bool(bake_first)
    if do_bake:
        bake_result = bake_lod_maps(context) if lod_objects(context) \
            else bake_product_maps(context, low_obj=obj)

    out_dir = website_dir(context)

    def _export_glb(target, path):
        previously_selected = [o for o in context.selected_objects]
        active = context.view_layer.objects.active
        for other in scene.objects:
            other.select_set(False)
        target.select_set(True)
        context.view_layer.objects.active = target
        try:
            bpy.ops.export_scene.gltf(
                filepath=path, export_format="GLB", use_selection=True,
                export_apply=True, export_animations=True,
                export_animation_mode="ACTIONS", export_cameras=False,
                export_lights=False, export_yup=True)
        finally:
            for other in scene.objects:
                other.select_set(other in previously_selected)
            context.view_layer.objects.active = active

    # Export every LOD tier; the site visitor picks quality at runtime.
    # product.glb mirrors the default tier for back-compat / harness.
    tiers = lod_objects(context) or {"medium": obj}
    default_level = {"LOW": "low", "MEDIUM": "medium", "HIGH": "high"}.get(
        str(getattr(site, "default_quality", "AUTO")).upper(), "medium")
    if default_level not in tiers:
        default_level = "medium" if "medium" in tiers else next(iter(tiers))
    lod_info: dict = {}
    for level, tier_obj in tiers.items():
        tier_path = os.path.join(out_dir, f"product_{level}.glb")
        _export_glb(tier_obj, tier_path)
        lod_info[level] = {
            "model": f"product_{level}.glb", "object": tier_obj.name,
            "faces": _face_count(tier_obj),
            "glbKB": round(os.path.getsize(tier_path) / 1024)
            if os.path.exists(tier_path) else 0}
    glb_path = os.path.join(out_dir, "product.glb")
    import shutil as _shutil
    _shutil.copyfile(os.path.join(out_dir, f"product_{default_level}.glb"), glb_path)

    # Sketchfab-style AR: USDZ for iOS Quick Look (GLB serves Android).
    usdz_path = os.path.join(out_dir, "product.usdz")
    if bool(getattr(site, "enable_ar", True)) and hasattr(bpy.ops.wm, "usd_export"):
        try:
            target = tiers[default_level]
            previously_selected = [o for o in context.selected_objects]
            active = context.view_layer.objects.active
            for other in scene.objects:
                other.select_set(False)
            target.select_set(True)
            context.view_layer.objects.active = target
            try:
                bpy.ops.wm.usd_export(filepath=usdz_path, selected_objects_only=True,
                                      export_animation=False, export_hair=False,
                                      export_uvmaps=True, export_normals=True,
                                      export_materials=True)
            finally:
                for other in scene.objects:
                    other.select_set(other in previously_selected)
                context.view_layer.objects.active = active
        except Exception:  # noqa: BLE001 - AR is an enhancement, never blocks
            usdz_path = ""
    else:
        usdz_path = ""

    # --- Step 0 + photo assets: prompt, Blender catalogue, 360 spins ---
    variant = str(getattr(site, "site_variant", "SHOWCASE")).upper()
    improved = improve_site_prompt(context)
    catalogue: list[dict] = []
    if bool(getattr(site, "render_catalogue", True)):
        try:
            catalogue = render_catalogue_images(context, out_dir, obj=obj)
        except Exception as exc:  # noqa: BLE001 - photos never block the GLB site
            site.prompt_status = f"Catalogue render skipped: {exc}"
    spins: list[dict] = []
    if variant == "CONFIGURATOR" or (variant == "SHOPIFY"
                                     and bool(getattr(site, "render_360", True))):
        try:
            finishes = site_prompts.parse_finishes(site.finish_options)
            spins = render_spin_images(
                context, out_dir, obj=obj,
                finishes=finishes if variant == "CONFIGURATOR" else finishes[:1])
        except Exception as exc:  # noqa: BLE001
            site.prompt_status = f"360 render skipped: {exc}"
    ai_assets: list[dict] = []
    if bool(getattr(site, "generate_ai_assets", False)):
        ai_assets = generate_ai_image_assets(context, out_dir, improved)
    images = catalogue + ai_assets
    finishes = site_prompts.parse_finishes(
        getattr(site, "finish_options", "Original"))

    animation_name = ""
    if obj.animation_data and obj.animation_data.action:
        animation_name = obj.animation_data.action.name
    product = {
        "name": site.brand_name or obj.name,
        "object": obj.name,
        "model": lod_info[default_level]["model"],
        "lods": lod_info,
        "defaultQuality": str(getattr(site, "default_quality", "AUTO")).upper(),
        "facesBefore": site.faces_before or _face_count(
            bpy.data.objects.get(site.product_object) if site.product_object else None),
        "facesAfter": lod_info[default_level]["faces"],
        "glbKB": lod_info[default_level]["glbKB"],
        "animation": animation_name,
        "animationStyle": getattr(site, "animation_style", "TURNTABLE"),
        "baked": [level for level, r in (bake_result or {}).get("lods", {}).items()
                  if r.get("baked")] or (bake_result or {}).get("baked", []),
        "variant": variant,
        "description": improved.get("improved", ""),
        "prompt": improved,
        "images": images,
        "spins": spins,
        "spin": spins[0] if spins else None,
        "finishes": finishes,
        "price": getattr(site, "product_price", ""),
        "currency": getattr(site, "product_currency", "USD"),
        "hotspots": site_prompts.parse_hotspots(getattr(site, "hotspots", "")),
        "cameraViews": site_prompts.CAMERA_VIEWS,
        "displayModes": site_prompts.DISPLAY_MODES,
        "ar": ({"usdz": "product.usdz", "glb": "product.glb"}
               if usdz_path and os.path.exists(usdz_path) else None),
    }
    shopify_data = None
    if variant == "SHOPIFY":
        shopify_data = site_prompts.build_shopify_product(
            product, price=site.product_price, currency=site.product_currency,
            sku=site.product_sku, vendor=site.product_vendor)
        product["shopify"] = shopify_data
    config = {"scrollScrub": bool(site.scroll_scrub), "dark": bool(site.dark_background),
              "accent": _accent_hex(site),
              "lightingPreset": getattr(site, "lighting_preset", "STUDIO"),
              "envIntensity": float(getattr(site, "env_intensity", 0.9)),
              "exposure": float(getattr(site, "exposure", 1.1)),
              "dioramaMode": bool(getattr(site, "diorama_mode", False)),
              "autoRotateIdle": bool(getattr(site, "auto_rotate_idle", True)),
              "defaultQuality": product["defaultQuality"]}
    site_data = web_cms.build_site_data(product, cms_languages(context),
                                        cms_entries(context), config)
    json_text = json.dumps(site_data, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, "content.json"), "w", encoding="utf-8") as handle:
        handle.write(json_text)
    locales_dir = os.path.join(out_dir, "locales")
    os.makedirs(locales_dir, exist_ok=True)
    for code, locale in site_data["locales"].items():
        with open(os.path.join(locales_dir, f"{code}.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(locale, handle, ensure_ascii=False, indent=2)
    html = site_template.render_site_html(json.dumps(site_data, ensure_ascii=False),
                                          accent_hex=config["accent"],
                                          dark=config["dark"], variant=variant)
    index_path = os.path.join(out_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as handle:
        handle.write(html)
    if shopify_data is not None:
        import csv as _csv
        shop_dir = os.path.join(out_dir, "shopify")
        os.makedirs(shop_dir, exist_ok=True)
        with open(os.path.join(shop_dir, "product.json"), "w", encoding="utf-8") as handle:
            json.dump(shopify_data, handle, ensure_ascii=False, indent=2)
        row = site_prompts.shopify_csv_row(product, shopify_data)
        with open(os.path.join(shop_dir, "products.csv"), "w", encoding="utf-8",
                  newline="") as handle:
            writer = _csv.DictWriter(handle, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)
        with open(os.path.join(shop_dir, "README.md"), "w", encoding="utf-8") as handle:
            handle.write(
                "# Shopify import\n\n"
                "Shopify Admin → Products → Import → upload `products.csv`, or "
                "use `product.json` with the Shopify Admin API / a theme app. "
                "Upload `../product.glb` under Files and reference it as the "
                "product's 3D model; upload `../images/*.jpg` as product media "
                "(the CSV's first image is the catalogue hero). The generated "
                "`../index.html` is the standalone storefront preview of the "
                "same product (gallery + interactive 3D + 360°).\n")

    # --- Harness: free port, validation, manifest, serve script ---
    preferred = int(getattr(site, "site_port", 8000) or 8000)
    # Probe the preferred port FIRST: if our own server is already live
    # there, find_free_port would skip over it and report a wrong port.
    probe = site_harness.probe_site(preferred, out_dir)
    if probe.get("is_showcase"):
        port = preferred
    else:
        port = site_harness.find_free_port(preferred)
        probe = site_harness.probe_site(port, out_dir)
    validation = site_harness.validate_site(out_dir) if getattr(site, "build_validate", True) else []
    manifest = site_harness.build_manifest(out_dir, product, config, port, validation)
    site_harness.write_serve_script(out_dir, port)
    url = f"http://127.0.0.1:{port}/"
    with open(os.path.join(out_dir, "README.md"), "w", encoding="utf-8") as handle:
        handle.write(
            "# Product showcase (generated from Blender)\n\n"
            f"**Live (if the server is running): {url}**\n\n"
            "Serve it (browsers block GLB loads from file://):\n\n"
            "```bash\n"
            f"cd this-folder\npython3 serve.py {port}   # or: python3 -m http.server {port}\n"
            "```\n\n"
            f"Then open {url} in a browser. "
            f"Harness: manifest.json records the build; validation "
            f"{'passed' if not validation else 'FAILED: ' + '; '.join(validation)}. "
            "To change any text or language: Blender → Muse Harness → Product "
            "Showcase → CMS, edit, then **Build Website** again. "
            "`content.json` / `locales/*.json` are the exported CMS data.\n")
    site.last_site_dir = out_dir
    return {"site_dir": out_dir, "index": index_path, "glb": glb_path,
            "lods": lod_info, "default_quality": default_level,
            "glb_kb": product["glbKB"], "languages": len(site_data["languages"]),
            "entries": len(cms_entries(context)), "animation": animation_name,
            "port": port, "url": url, "running": bool(probe.get("is_showcase")),
            "probe": probe, "validation": validation, "manifest": manifest,
            "bake": bake_result, "variant": variant, "images": images,
            "spins": spins, "shopify": shopify_data, "prompt": improved}
