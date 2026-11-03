"""Operators: async Muse generation, material/GN application, utilities.

Generation runs on a worker thread (Meta API calls take seconds); results
are applied back on the main thread by a modal timer operator, so the
Blender UI never freezes.
"""

from __future__ import annotations

import os
import threading
import time

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty

from . import api_client, nodes, utils

_JOBS: dict[str, dict] = {}


def _launch(job_id: str, fn) -> None:
    def runner():
        try:
            _JOBS[job_id].update(result=fn(), error="")
        except Exception as exc:  # noqa: BLE001 - reported in the UI
            _JOBS[job_id].update(result=None, error=str(exc))
        finally:
            _JOBS[job_id]["done"] = True

    _JOBS[job_id] = {"done": False, "result": None, "error": ""}
    threading.Thread(target=runner, daemon=True).start()


def _apply_generated_image(context, result, prompt: str,
                           apply_material: bool, apply_gn: bool) -> str:
    """Save + load a generated image, record history, apply it. Main thread."""
    scene = context.scene
    filepath = utils.save_image_bytes(result.image_bytes, result.image_format, prompt)
    image = utils.load_blender_image(filepath, name=f"Muse_{utils.slugify(prompt)}")
    item = scene.muse_history.add()
    item.name = image.name
    item.prompt = prompt
    item.filepath = filepath
    item.image_name = image.name
    item.created = time.strftime("%Y-%m-%d %H:%M")
    scene.muse.history_index = len(scene.muse_history) - 1

    applied: list[str] = []
    obj = utils.active_mesh_object(context)
    material = None
    if apply_material:
        if obj is None:
            applied.append("no mesh selected (image saved to Image Editor data)")
        else:
            utils.ensure_uv_map(obj)
            material = nodes.apply_image_to_object(
                obj, image, use_bump=scene.muse.use_bump,
                use_roughness=scene.muse.use_roughness)
            applied.append(f"material on {obj.name}")
    if apply_gn:
        if obj is None:
            applied.append("no mesh selected for Geometry Nodes")
        else:
            if material is None and scene.muse.auto_apply:
                utils.ensure_uv_map(obj)
                material = nodes.apply_image_to_object(
                    obj, image, use_bump=scene.muse.use_bump,
                    use_roughness=scene.muse.use_roughness)
            nodes.add_gn_modifier(obj, image=image, material=material)
            applied.append(f"Geometry Nodes on {obj.name}")
    context.view_layer.update()
    return "; ".join(applied) if applied else "image loaded (open it in the Image Editor)"


class _AsyncOperator:
    """Modal plumbing shared by the network operators."""

    _job_id = ""
    _timer = None

    def _begin(self, context, job_id, fn):
        self._job_id = job_id
        _launch(job_id, fn)
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.25, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC":
            self._cleanup(context)
            context.scene.muse.is_generating = False
            context.scene.muse.status = "Cancelled (request may still finish server-side)."
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        job = _JOBS.get(self._job_id)
        if job is None or not job["done"]:
            return {"PASS_THROUGH"}
        self._cleanup(context)
        context.scene.muse.is_generating = False
        if job["error"]:
            context.scene.muse.status = f"Error: {job['error']}"
            self.report({"ERROR"}, job["error"])
            return {"CANCELLED"}
        self._on_result(context, job["result"])
        return {"FINISHED"}

    def _cleanup(self, context):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        _JOBS.pop(self._job_id, None)

    def _on_result(self, context, result):  # overridden
        raise NotImplementedError


class MUSE_OT_generate(bpy.types.Operator, _AsyncOperator):
    bl_idname = "muse.generate"
    bl_label = "Generate with Muse Image"
    bl_description = "Generate a texture/image with Meta Muse Image 1.0"
    bl_options = {"REGISTER"}

    mode: EnumProperty(items=[("GENERATE", "Generate", ""), ("EDIT", "Edit", "")],
                       default="GENERATE", options={"HIDDEN"})
    apply_material: BoolProperty(default=True, options={"HIDDEN"})
    apply_gn: BoolProperty(default=False, options={"HIDDEN"})

    _prompt = ""

    def invoke(self, context, event):
        scene = context.scene
        if scene.muse.is_generating:
            self.report({"WARNING"}, "A generation is already running.")
            return {"CANCELLED"}
        key, source, base_url, model = utils.api_settings(context)
        if not key:
            scene.muse.status = f"No API key: {source}"
            self.report({"ERROR"}, scene.muse.status)
            return {"CANCELLED"}

        if self.mode == "EDIT":
            if not scene.muse_history:
                self.report({"ERROR"}, "Generate an image first, then edit it.")
                return {"CANCELLED"}
            reference_path = scene.muse_history[-1].filepath
            if not reference_path or not os.path.exists(reference_path):
                self.report({"ERROR"}, "Last generated file is missing on disk.")
                return {"CANCELLED"}
            with open(reference_path, "rb") as handle:
                reference = handle.read()
            prompt = scene.muse.edit_prompt.strip()
            self._prompt = prompt
            fn = lambda: api_client.edit_image(  # noqa: E731
                prompt, [reference], key, size=scene.muse.size,
                base_url=base_url, model=model)
            verb = "Editing"
        else:
            target_obj = utils.active_mesh_object(context)
            raw_prompt = scene.muse.prompt
            if self.apply_gn and target_obj is not None and target_obj.muse.gn_prompt:
                raw_prompt = target_obj.muse.gn_prompt
            prompt = utils.build_prompt(raw_prompt, scene.muse.style,
                                        scene.muse.tileable)
            self._prompt = prompt
            fn = lambda: api_client.generate_image(  # noqa: E731
                prompt, key, size=scene.muse.size, base_url=base_url, model=model)
            verb = "Generating"

        scene.muse.is_generating = True
        scene.muse.status = f"{verb} with {model} … (key from {source})"
        return self._begin(context, f"muse-{time.time_ns()}", fn)

    def _on_result(self, context, result):
        detail = _apply_generated_image(context, result, self._prompt,
                                        self.apply_material, self.apply_gn)
        context.scene.muse.status = f"Done: {detail}."
        self.report({"INFO"}, context.scene.muse.status)


class MUSE_OT_test_connection(bpy.types.Operator, _AsyncOperator):
    bl_idname = "muse.test_connection"
    bl_label = "Test Connection"
    bl_description = "Check the Meta API key against https://api.meta.ai/v1"

    def invoke(self, context, event):
        key, source, base_url, _model = utils.api_settings(context)
        context.scene.muse.status = f"Testing connection (key from {source}) …"
        fn = lambda: api_client.test_connection(key, base_url=base_url)  # noqa: E731
        return self._begin(context, f"muse-test-{time.time_ns()}", fn)

    def _on_result(self, context, result):
        ok, message = result
        context.scene.muse.status = message
        self.report({"INFO"} if ok else {"ERROR"}, message)


class MUSE_OT_apply_history(bpy.types.Operator):
    bl_idname = "muse.apply_history"
    bl_label = "Apply Texture"
    bl_description = "Apply this generated image to the active mesh"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(default=-1, options={"HIDDEN"})
    apply_gn: BoolProperty(default=False, options={"HIDDEN"})

    def execute(self, context):
        scene = context.scene
        index = self.index if self.index >= 0 else scene.muse.history_index
        if not (0 <= index < len(scene.muse_history)):
            self.report({"ERROR"}, "No generated image selected.")
            return {"CANCELLED"}
        item = scene.muse_history[index]
        image = bpy.data.images.get(item.image_name)
        if image is None and item.filepath and os.path.exists(item.filepath):
            image = utils.load_blender_image(item.filepath, name=item.image_name)
        if image is None:
            self.report({"ERROR"}, "Image data is gone; regenerate it.")
            return {"CANCELLED"}
        obj = utils.active_mesh_object(context)
        if obj is None:
            self.report({"ERROR"}, "Select a mesh object first.")
            return {"CANCELLED"}
        utils.ensure_uv_map(obj)
        material = nodes.apply_image_to_object(
            obj, image, use_bump=scene.muse.use_bump,
            use_roughness=scene.muse.use_roughness)
        if self.apply_gn:
            nodes.add_gn_modifier(obj, image=image, material=material)
        scene.muse.status = f"Applied {image.name} to {obj.name}."
        return {"FINISHED"}


class MUSE_OT_add_gn_modifier(bpy.types.Operator):
    bl_idname = "muse.add_gn_modifier"
    bl_label = "Add Muse GN Modifier"
    bl_description = "Add the Muse Geometry Nodes modifier (texture-driven displacement)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = utils.active_mesh_object(context)
        if obj is None:
            self.report({"ERROR"}, "Select a mesh object first.")
            return {"CANCELLED"}
        image = None
        if context.scene.muse_history:
            image = bpy.data.images.get(context.scene.muse_history[-1].image_name)
        modifier = nodes.add_gn_modifier(obj, image=image)
        context.scene.muse.status = (
            f"Added {modifier.name} to {obj.name}. Generate a texture or pick one "
            "from History to feed its Image input.")
        return {"FINISHED"}


class MUSE_OT_add_gn_group_node(bpy.types.Operator):
    bl_idname = "muse.add_gn_group_node"
    bl_label = "Muse GN Texture"
    bl_description = "Add a Muse GN Texture group node to the Geometry Nodes tree"

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return (space and space.type == "NODE_EDITOR"
                and getattr(space, "tree_type", "") == "GeometryNodeTree"
                and space.edit_tree is not None)

    def execute(self, context):
        group = nodes.ensure_gn_group()
        node = context.space_data.edit_tree.nodes.new("GeometryNodeGroup")
        node.node_tree = group
        node.label = "Muse GN Texture"
        return {"FINISHED"}


class MUSE_OT_open_textures_folder(bpy.types.Operator):
    bl_idname = "muse.open_textures_folder"
    bl_label = "Open Textures Folder"

    def execute(self, context):
        bpy.ops.wm.path_open(filepath=utils.textures_dir())
        return {"FINISHED"}


class MUSE_OT_clear_history(bpy.types.Operator):
    bl_idname = "muse.clear_history"
    bl_label = "Clear History"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        context.scene.muse_history.clear()
        context.scene.muse.history_index = -1
        context.scene.muse.status = "History cleared (files stay on disk)."
        return {"FINISHED"}


classes = (
    MUSE_OT_generate,
    MUSE_OT_test_connection,
    MUSE_OT_apply_history,
    MUSE_OT_add_gn_modifier,
    MUSE_OT_add_gn_group_node,
    MUSE_OT_open_textures_folder,
    MUSE_OT_clear_history,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
