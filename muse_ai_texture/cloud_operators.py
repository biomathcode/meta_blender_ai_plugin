"""Operators: render the scene camera (viewport) on Modal.

The current scene — including unsaved changes — is saved to a temporary
copy (the user's file is not overwritten), uploaded by the generated Modal
app, rendered there (Cycles GPU or CPU, scene settings preserved), and the
PNG/MP4 is downloaded into `muse_cloud_renders/` next to the .blend and
loaded back into Blender. The Modal run happens on a worker thread; results
are applied on the main thread by a modal timer operator.

Pattern: https://modal.com/docs/examples/blender_video
"""

from __future__ import annotations

import os
import threading
import time

import bpy
from bpy.props import EnumProperty

from . import modal_client, utils

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


class _CloudAsyncOperator:
    _job_id = ""
    _timer = None

    def _begin(self, context, job_id, fn):
        self._job_id = job_id
        _launch(job_id, fn)
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.5, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC":
            self._cleanup(context)
            context.scene.muse_cloud.is_rendering = False
            context.scene.muse_cloud.status = (
                "Cancelled in Blender (the Modal run may still finish server-side).")
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        job = _JOBS.get(self._job_id)
        if job is None or not job["done"]:
            return {"PASS_THROUGH"}
        self._cleanup(context)
        context.scene.muse_cloud.is_rendering = False
        if job["error"]:
            context.scene.muse_cloud.status = f"Error: {job['error']}"
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


class MUSE_OT_cloud_render(bpy.types.Operator, _CloudAsyncOperator):
    bl_idname = "muse.cloud_render"
    bl_label = "Render Camera in Cloud (Modal)"
    bl_description = ("Upload the current scene to Modal and render the "
                      "active camera there (scene render settings preserved)")
    bl_options = {"REGISTER"}

    mode: EnumProperty(
        items=[("STILL", "Still", ""), ("ANIMATION", "Animation", "")],
        default="STILL", options={"HIDDEN"})

    def invoke(self, context, event):
        scene = context.scene
        cloud = scene.muse_cloud
        if cloud.is_rendering:
            self.report({"WARNING"}, "A cloud render is already running.")
            return {"CANCELLED"}
        if scene.camera is None:
            cloud.status = "No active camera: add/set a camera first (viewport render needs one)."
            self.report({"ERROR"}, cloud.status)
            return {"CANCELLED"}
        creds, app_name, cli_path = utils.modal_settings(context)
        if not creds.ok:
            cloud.status = f"No Modal tokens: {creds.source}"
            self.report({"ERROR"}, cloud.status)
            return {"CANCELLED"}
        if not cli_path:
            cloud.status = ("Modal CLI not found. Install it with "
                            "`pip install modal` or set Modal CLI Path in Preferences.")
            self.report({"ERROR"}, cloud.status)
            return {"CANCELLED"}

        output_dir = utils.cloud_renders_dir()
        # Save a copy so unsaved viewport changes are rendered, without
        # overwriting (or changing the path of) the user's own file.
        blend_path = os.path.join(output_dir, "_muse_cloud_scene.blend")
        try:
            bpy.ops.wm.save_as_mainfile(filepath=blend_path, copy=True)
        except RuntimeError as exc:
            cloud.status = f"Could not save a scene copy for upload: {exc}"
            self.report({"ERROR"}, cloud.status)
            return {"CANCELLED"}
        app_path = modal_client.write_modal_app(
            output_dir, app_name=app_name, gpu=cloud.gpu,
            use_gpu=cloud.use_gpu, max_containers=cloud.max_containers)

        mode = "animation" if self.mode == "ANIMATION" else "still"
        frame = scene.frame_current
        fn = lambda: modal_client.run_cloud_render(  # noqa: E731
            cli_path, app_path, blend_path, output_dir, creds,
            mode=mode, frame=frame,
            frame_start=scene.frame_start, frame_end=scene.frame_end,
            frame_step=cloud.frame_step, fps=scene.render.fps)
        cloud.is_rendering = True
        what = ("animation frames " + str(scene.frame_start) + "–"
                + str(scene.frame_end) if mode == "animation"
                else "frame " + str(frame))
        where = "GPU " + cloud.gpu if cloud.use_gpu else "CPU"
        cloud.status = (
            f"Rendering {what} from camera '{scene.camera.name}' on Modal "
            f"({where}; tokens from {creds.source}) …")
        return self._begin(context, f"muse-cloud-{time.time_ns()}", fn)

    def _on_result(self, context, result):
        cloud = context.scene.muse_cloud
        shown = result.video_path or result.still_path
        if result.still_path and os.path.exists(result.still_path):
            image = bpy.data.images.load(result.still_path, check_existing=False)
            image.name = "CloudRender_" + os.path.basename(result.still_path)
            shown = result.still_path
        cloud.last_result = shown
        cloud.status = f"Done: cloud render saved to {shown}"
        self.report({"INFO"}, cloud.status)


class MUSE_OT_cloud_test(bpy.types.Operator):
    bl_idname = "muse.cloud_test"
    bl_label = "Test Modal"
    bl_description = "Check Modal tokens (Preferences / .env / environment) and the Modal CLI"

    def execute(self, context):
        creds, app_name, cli_path = utils.modal_settings(context)
        if not creds.ok:
            message = f"Modal tokens missing: {creds.source}"
            context.scene.muse_cloud.status = message
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        if not cli_path:
            message = ("Modal tokens OK "
                       f"({creds.source}), but the Modal CLI was not found. "
                       "Install it with `pip install modal`.")
            context.scene.muse_cloud.status = message
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        message = (f"Modal ready: tokens from {creds.source}; "
                   f"CLI at {cli_path}; app '{app_name}'.")
        context.scene.muse_cloud.status = message
        self.report({"INFO"}, message)
        return {"FINISHED"}


class MUSE_OT_open_cloud_folder(bpy.types.Operator):
    bl_idname = "muse.open_cloud_folder"
    bl_label = "Open Cloud Renders Folder"

    def execute(self, context):
        bpy.ops.wm.path_open(filepath=utils.cloud_renders_dir())
        return {"FINISHED"}


classes = (MUSE_OT_cloud_render, MUSE_OT_cloud_test, MUSE_OT_open_cloud_folder)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
