"""Operators: SAM 3.1 (Meta Model API) segmentation of Gaussian splats.

Flow (type the objects, one click):

  1. Export the active splat's points (position / colour / opacity) to
     input.npz in a timestamped job folder.
  2. Run splat_worker.py in a separate Python process: it renders orbit
     views, segments exactly the typed objects with SAM 3.1 on the Meta
     Model API (the addon's existing Meta key — no HF token, no local
     weights), votes masks back onto the Gaussians with a depth test,
     and splits same-object clusters into instances.
  3. Back on Blender's main thread, store the per-point instance ids as a
     `segment_id` attribute and create one native splat object per
     instance via a Geometry Nodes Delete Geometry filter (Blender 5.4's
     point delete path) — evaluated copies preserve radiance:base, scale
     and rotation untouched. Nothing is deleted: unlabelled points stay
     available as the background object, and the source is only hidden.

Worker Python resolution: Addon Preferences override, then the
project-local worker env created by "Create Worker Env"
(<project>/.venv-splat, uv-managed when uv is available), then
python3.11/python3 on PATH (checked with muse.splat_check_setup). The env
belongs with the project — never in $HOME or /tmp, never the system
interpreter.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time

import bpy
import numpy as np

from . import sam_client
from . import splat_core as core
from . import utils

WORKER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "splat_worker.py")
_SPLAT_JOBS: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Worker environment
# ---------------------------------------------------------------------------

def _project_root() -> str:
    """Parent of the addon package: the project directory.

    In this repo that is the repository root; when the addon is installed
    it is the folder containing the addon. The worker environment lives
    inside it (.venv-splat), where project tooling expects environments.
    """
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def worker_env_dir() -> str:
    return os.path.join(_project_root(), ".venv-splat")


def _forward_env_file(context) -> str:
    """First existing .env the worker should also search for META_API_KEY.

    The resolved key itself is forwarded via the META_API_KEY environment
    variable; this path is the fallback so the worker finds the key even
    when it is only in a .env file (Preferences .env File, .blend folder,
    addon folder, or project/repo root) and the env forwarding is bypassed.
    """
    candidates: list[str] = []
    prefs = utils._prefs()
    if prefs is not None and getattr(prefs, "env_file", ""):
        candidates.append(bpy.path.abspath(prefs.env_file))
    if bpy.data.filepath:
        candidates.append(os.path.join(
            os.path.dirname(bpy.path.abspath(bpy.data.filepath)), ".env"))
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    candidates.append(os.path.join(_project_root(), ".env"))
    candidates.append(os.path.join(os.getcwd(), ".env"))
    candidates.append(os.path.join(os.path.expanduser("~"), ".env"))
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return ""


def _venv_python(env_dir: str = "") -> str:
    env_dir = env_dir or worker_env_dir()
    if os.name == "nt":
        return os.path.join(env_dir, "Scripts", "python.exe")
    return os.path.join(env_dir, "bin", "python")


def worker_python(context) -> tuple[str, str]:
    """Return (python_path, source_label) for the segmentation worker."""
    prefs = utils._prefs()
    if prefs is not None and getattr(prefs, "splat_python", ""):
        path = bpy.path.abspath(prefs.splat_python)
        return path, "Addon Preferences"
    venv = _venv_python()
    if os.path.isfile(venv):
        return venv, "project worker env (.venv-splat)"
    for candidate in ("python3.11", "python3.12", "python3.10", "python3"):
        found = shutil.which(candidate)
        if found:
            return found, f"{candidate} on PATH (run Check Worker Setup)"
    return "", "not found — click Create Worker Env"


def _run_logged(command: list[str], log_handle) -> None:
    log_handle.write("+ " + " ".join(command) + "\n")
    log_handle.flush()
    proc = subprocess.run(command, stdout=log_handle,
                          stderr=subprocess.STDOUT, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed (exit {proc.returncode}): "
                           f"{' '.join(command[:3])} … — see the setup log")


def _tail(path: str, lines: int = 15) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return "\n".join(handle.read().splitlines()[-lines:])
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Async plumbing (same thread + modal-timer pattern as operators.py,
# with live status from the job's progress message)
# ---------------------------------------------------------------------------

def _launch_splat(job_id: str, fn) -> None:
    def runner():
        job = _SPLAT_JOBS[job_id]
        try:
            job.update(result=fn(job), error="")
        except Exception as exc:  # noqa: BLE001 - reported in the UI
            job.update(result=None, error=str(exc))
        finally:
            job["done"] = True

    _SPLAT_JOBS[job_id] = {"done": False, "result": None, "error": "",
                           "message": "", "cancel": False, "proc": None}
    threading.Thread(target=runner, daemon=True).start()


class _SplatAsync:
    """Modal plumbing shared by the splat operators."""

    _job_id = ""
    _timer = None

    def _begin_splat(self, context, job_id, fn):
        self._job_id = job_id
        _launch_splat(job_id, fn)
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.4, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        settings = context.scene.muse_splat
        job = _SPLAT_JOBS.get(self._job_id)
        if event.type == "ESC":
            if job is not None:
                job["cancel"] = True
                proc = job.get("proc")
                if proc is not None:
                    try:
                        proc.terminate()
                    except OSError:
                        pass
            self._cleanup_splat(context)
            settings.is_processing = False
            settings.status = "Cancelled. Partial views stay in the job folder."
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        if job is None:
            self._cleanup_splat(context)
            settings.is_processing = False
            return {"CANCELLED"}
        if job.get("message"):
            settings.status = job["message"]
        if not job["done"]:
            return {"PASS_THROUGH"}
        self._cleanup_splat(context)
        settings.is_processing = False
        if job["error"]:
            settings.status = f"Error: {job['error']}"
            self.report({"ERROR"}, job["error"])
            return {"CANCELLED"}
        self._on_result(context, job["result"])
        return {"FINISHED"}

    def _cleanup_splat(self, context):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        _SPLAT_JOBS.pop(self._job_id, None)

    def _on_result(self, context, result):  # overridden
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Splat import / export / separation (Blender main thread)
# ---------------------------------------------------------------------------

def _resolve_splat_object(context, settings):
    if settings.source_object:
        obj = bpy.data.objects.get(settings.source_object)
        if obj is not None and obj.type == "POINTCLOUD":
            return obj
    active = context.view_layer.objects.active
    if active is not None and active.type == "POINTCLOUD":
        return active
    for candidate in context.selected_objects:
        if candidate.type == "POINTCLOUD":
            return candidate
    return None


def _do_import_spz(context, settings) -> bpy.types.Object:
    path = bpy.path.abspath(settings.spz_path or "")
    if not path or not os.path.isfile(path):
        raise RuntimeError("Pick an existing .spz file first (SPZ File field).")
    if not hasattr(bpy.ops.wm, "spz_import"):
        raise RuntimeError("This Blender has no .spz importer — "
                           "Gaussian splat import needs Blender 5.3+.")
    before = set(bpy.data.objects)
    bpy.ops.wm.spz_import(filepath=path)
    created = [obj for obj in bpy.data.objects
               if obj not in before and obj.type == "POINTCLOUD"]
    if not created:
        raise RuntimeError(f"No splat point cloud was imported from {path}.")
    obj = created[0]
    settings.source_object = obj.name
    for other in context.selected_objects:
        other.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    return obj


def _export_splat(obj, input_path: str) -> int:
    """Write positions/colors/opacity for the worker. Returns point count."""
    pointcloud = obj.data
    count = len(pointcloud.points)
    positions = np.empty(count * 3, dtype=np.float32)
    pointcloud.attributes["position"].data.foreach_get("vector", positions)
    radiance = np.empty(count * 4, dtype=np.float32)
    pointcloud.attributes["radiance:base"].data.foreach_get("vector", radiance)
    radiance = radiance.reshape(count, 4)
    colors = core.sh_to_rgb(radiance[:, :3])
    # The splat may be transformed: bake the world transform into the
    # exported points so worker cameras and Blender points agree.
    matrix = np.array(obj.matrix_world, dtype=np.float64)
    world = (positions.reshape(count, 3).astype(np.float64) @ matrix[:3, :3].T
             + matrix[:3, 3])
    os.makedirs(os.path.dirname(input_path), exist_ok=True)
    np.savez(input_path, positions=world.astype(np.float32),
             colors=colors.astype(np.float32),
             opacity=radiance[:, 3].astype(np.float32))
    return count


def _sock(sockets, name: str, index: int):
    try:
        return sockets[name]
    except (KeyError, TypeError, IndexError):
        return sockets[index]


def _make_filter_group(keep_id: int):
    """Geometry Nodes group keeping only points with segment_id == keep_id.

    This is Blender 5.4's point delete path: Delete Geometry on the POINT
    domain drops every other Gaussian while position, radiance:base,
    scale and rotation pass through untouched.
    """
    group = bpy.data.node_groups.new(f"Muse Splat Filter {keep_id}",
                                     "GeometryNodeTree")
    group.interface.new_socket("Geometry", in_out="INPUT",
                               socket_type="NodeSocketGeometry")
    group.interface.new_socket("Geometry", in_out="OUTPUT",
                               socket_type="NodeSocketGeometry")
    inp = group.nodes.new("NodeGroupInput")
    out = group.nodes.new("NodeGroupOutput")
    out.location.x = 520
    named = group.nodes.new("GeometryNodeInputNamedAttribute")
    named.data_type = "INT"
    named.location = (-40, -160)
    _sock(named.inputs, "Name", 0).default_value = "segment_id"
    compare = group.nodes.new("FunctionNodeCompare")
    compare.data_type = "INT"
    compare.operation = "NOT_EQUAL"
    compare.location = (160, -160)
    compare.inputs[1].default_value = int(keep_id)
    delete = group.nodes.new("GeometryNodeDeleteGeometry")
    delete.domain = "POINT"
    delete.location = (340, 0)
    group.links.new(_sock(inp.outputs, "Geometry", 0),
                    _sock(delete.inputs, "Geometry", 0))
    group.links.new(_sock(named.outputs, "Attribute", 0), compare.inputs[0])
    group.links.new(compare.outputs[0], _sock(delete.inputs, "Selection", 1))
    group.links.new(delete.outputs[0], _sock(out.inputs, "Geometry", 0))
    return group


def _set_point_attribute(pointcloud, name: str, data_type: str,
                         values: np.ndarray, key: str = "value") -> None:
    existing = pointcloud.attributes.get(name)
    if existing is not None:
        pointcloud.attributes.remove(existing)
    attr = pointcloud.attributes.new(name=name, type=data_type, domain="POINT")
    attr.data.foreach_set(key, np.ascontiguousarray(values))


def _separate_splat(context, source, instance_ids: np.ndarray,
                    confidence: np.ndarray, instances: list[dict],
                    keep_background: bool) -> list[tuple[str, int, str]]:
    """Create one native splat object per instance. Returns [(name, points, prompt)].

    `instances` includes the id-0 background entry. The source keeps the
    full data (only hidden) — separation never deletes Gaussians.
    """
    pointcloud = source.data
    _set_point_attribute(pointcloud, "segment_id", "INT",
                         instance_ids.astype(np.int32))
    if confidence is not None:
        _set_point_attribute(pointcloud, "segment_confidence", "FLOAT",
                             confidence.astype(np.float32))
    source["splat_instances"] = json.dumps(instances)
    # Viewport-hidden objects are skipped by the depsgraph, which would
    # silently evaluate the filter modifier to the unfiltered source.
    # Force visibility during separation; the source is hidden again at
    # the end (it stays in the file as the untouched backup).
    source.hide_viewport = False
    source.hide_render = False
    collection = (source.users_collection[0] if source.users_collection
                  else context.collection)
    base = source.name
    created: list[tuple[str, int, str]] = []
    for entry in instances:
        keep_id = int(entry["id"])
        points = int(entry["points"])
        if points <= 0 or (keep_id == 0 and not keep_background):
            continue
        prompt = entry.get("prompt", "")
        dup = source.copy()
        dup.name = f"_muse_splat_tmp_{keep_id}"
        dup.hide_viewport = False
        dup.hide_render = False
        collection.objects.link(dup)
        group = _make_filter_group(keep_id)
        modifier = dup.modifiers.new("Muse Segment Filter", "NODES")
        modifier.node_group = group
        context.view_layer.update()
        evaluated = dup.evaluated_get(context.evaluated_depsgraph_get())
        new_data = evaluated.data.copy()
        if len(new_data.points) != points:
            bpy.data.objects.remove(dup, do_unlink=True)
            bpy.data.node_groups.remove(group)
            raise RuntimeError(
                f"Segment filter for '{prompt or 'background'}' kept "
                f"{len(new_data.points):,} points, expected {points:,} — "
                "the modifier did not evaluate (hidden object or "
                "stale depsgraph). Nothing was separated.")
        if keep_id == 0:
            name = f"{base}_background"
        else:
            name = f"{base}_{utils.slugify(prompt or 'part', 24)}_{keep_id:02d}"
        new_obj = bpy.data.objects.new(name, new_data)
        new_obj.matrix_world = source.matrix_world.copy()
        collection.objects.link(new_obj)
        new_obj["splat_prompt"] = prompt
        new_obj["splat_points"] = points
        new_obj["splat_source"] = base
        bpy.data.objects.remove(dup, do_unlink=True)
        bpy.data.node_groups.remove(group)
        created.append((new_obj.name, points, prompt))
    source.hide_viewport = True
    source.hide_render = True
    for obj in context.selected_objects:
        obj.select_set(False)
    for name, _points, _prompt in created:
        bpy.data.objects[name].select_set(True)
    if created:
        context.view_layer.objects.active = bpy.data.objects[created[0][0]]
    context.view_layer.update()
    return created


def _summary(created: list[tuple[str, int, str]], total: int) -> str:
    parts = [f"{name} ({points:,} pts)" + (f" [{prompt}]" if prompt else "")
             for name, points, prompt in created]
    return (f"Separated {total:,} Gaussians into {len(created)} objects: "
            + "; ".join(parts) + ".")


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class MUSE_OT_splat_import(bpy.types.Operator):
    bl_idname = "muse.splat_import"
    bl_label = "Import SPZ Splat"
    bl_description = "Import the .spz file as a native Gaussian splat point cloud"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.muse_splat
        try:
            obj = _do_import_spz(context, settings)
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        settings.status = (
            f"Imported {obj.name}: {len(obj.data.points):,} Gaussians. "
            "Type the objects to segment, then Segment & Separate.")
        self.report({"INFO"}, settings.status)
        return {"FINISHED"}


class MUSE_OT_splat_check_setup(bpy.types.Operator, _SplatAsync):
    bl_idname = "muse.splat_check_setup"
    bl_label = "Check Worker Setup"
    bl_description = "Check the splat worker Python and the Meta key for SAM 3.1"

    def invoke(self, context, event):
        settings = context.scene.muse_splat
        python, source = worker_python(context)
        if not python or not os.path.isfile(python):
            settings.status = ("No worker Python found. Click Create Worker Env "
                               "(one-time, light install — SAM 3.1 runs on the API).")
            self.report({"ERROR"}, settings.status)
            return {"CANCELLED"}
        settings.is_processing = True
        settings.status = f"Checking worker ({source})…"
        key, key_source, _url, _model = utils.api_settings(context)

        env_file = _forward_env_file(context)

        def fn(_job):
            env = dict(os.environ)
            if key:
                env["META_API_KEY"] = key
            check_cmd = [python, WORKER_SCRIPT, "--check"]
            if env_file:
                env["MUSE_ENV_FILE"] = env_file
                check_cmd += ["--env-file", env_file]
            proc = subprocess.run(check_cmd,
                                  capture_output=True, text=True, timeout=180,
                                  env=env)
            lines = [line for line in (proc.stdout or "").splitlines()
                     if line.strip().startswith("{")]
            if not lines:
                raise RuntimeError("Worker check produced no output: "
                                   + (proc.stderr or "")[-400:])
            info = json.loads(lines[-1])
            if info.get("ready"):
                auth = (f"Meta key: {key_source} (same key as Muse Image)."
                        if info.get("meta_key") else
                        "No Meta key: add META_API_KEY to a .env file or "
                        "Addon Preferences — SAM 3.1 uses that same key.")
                return (f"Worker ready ({source}): numpy {info.get('numpy')}, "
                        f"pillow {info.get('pillow') or '?'}, SAM parser OK. "
                        f"{auth} SAM 3.1 ({info.get('sam_model')}) runs on the "
                        "Meta Model API — no weights or GPU needed.")
            missing = []
            if not info.get("pillow"):
                missing.append("pillow")
            if not info.get("meta_sam_parser"):
                missing.append("meta-sam-parser")
            return (f"Worker Python found ({source}) but missing: "
                    f"{', '.join(missing) or 'unknown'}. Click Create Worker Env "
                    "to install everything into a dedicated venv.")

        return self._begin_splat(context, f"splat-check-{time.time_ns()}", fn)

    def _on_result(self, context, result):
        context.scene.muse_splat.status = str(result)
        self.report({"INFO"}, str(result))


_SETUP_PACKAGES = ("numpy", "pillow", "meta-sam-parser")


class MUSE_OT_splat_setup_worker(bpy.types.Operator, _SplatAsync):
    bl_idname = "muse.splat_setup_worker"
    bl_label = "Create Worker Env"
    bl_description = ("One-time: create the project-local .venv-splat env "
                      "(uv when available) and install the light worker "
                      "deps (numpy + pillow + SAM parser). SAM 3.1 itself "
                      "runs on the Meta API — nothing else to download")
    bl_options = {"REGISTER"}

    def invoke(self, context, event):
        settings = context.scene.muse_splat
        if settings.is_processing:
            self.report({"WARNING"}, "Already working — wait for it to finish.")
            return {"CANCELLED"}
        uv = shutil.which("uv")
        base = next((shutil.which(name) for name in
                     ("python3.11", "python3.12", "python3.10", "python3")
                     if shutil.which(name)), "")
        if not uv and not base:
            settings.status = ("Neither uv nor Python 3.10+ found on PATH to "
                               "build the worker env.")
            self.report({"ERROR"}, settings.status)
            return {"CANCELLED"}
        settings.is_processing = True
        settings.status = "Creating project worker env .venv-splat…"
        env_dir = worker_env_dir()
        log_path = os.path.join(_project_root(), ".venv-splat-setup.log")
        key, _key_source, _url, _model = utils.api_settings(context)

        def fn(job):
            venv_python = _venv_python(env_dir)
            with open(log_path, "w", encoding="utf-8") as log:
                if not os.path.isfile(venv_python):
                    job["message"] = "Creating project worker env (.venv-splat)…"
                    if uv:
                        _run_logged([uv, "venv", env_dir, "--python", "3.11"], log)
                    else:
                        _run_logged([base, "-m", "venv", env_dir], log)
                job["message"] = ("Installing worker deps (numpy + pillow + "
                                  "SAM parser) into .venv-splat…")
                if uv:
                    _run_logged([uv, "pip", "install", "--python", venv_python,
                                 *_SETUP_PACKAGES], log)
                else:
                    _run_logged([venv_python, "-m", "pip", "install", "--upgrade",
                                 "pip"], log)
                    _run_logged([venv_python, "-m", "pip", "install",
                                 *_SETUP_PACKAGES], log)
            env = dict(os.environ)
            if key:
                env["META_API_KEY"] = key
            check_cmd = [venv_python, WORKER_SCRIPT, "--check"]
            forwarded = _forward_env_file(context)
            if forwarded:
                env["MUSE_ENV_FILE"] = forwarded
                check_cmd += ["--env-file", forwarded]
            proc = subprocess.run(check_cmd,
                                  capture_output=True, text=True, timeout=180,
                                  env=env)
            lines = [line for line in (proc.stdout or "").splitlines()
                     if line.strip().startswith("{")]
            info = json.loads(lines[-1]) if lines else {}
            if info.get("ready"):
                message = "Worker env ready (numpy + pillow + SAM parser)."
                if info.get("meta_key"):
                    message += (" Meta key found — SAM 3.1 is ready on the "
                                "Meta Model API. No weights to download.")
                else:
                    message += (" Add META_API_KEY (same key as Muse Image) "
                                "to a .env file or Preferences, then segment.")
                return message
            raise RuntimeError("Worker env created but the SAM parser is not "
                               f"importable — see {log_path}:\n{_tail(log_path)}")

        return self._begin_splat(context, f"splat-setup-{time.time_ns()}", fn)

    def _on_result(self, context, result):
        context.scene.muse_splat.status = str(result)
        self.report({"INFO"}, str(result))


class MUSE_OT_splat_segment(bpy.types.Operator, _SplatAsync):
    bl_idname = "muse.splat_segment"
    bl_label = "Segment & Separate"
    bl_description = ("Render orbit views, segment only the objects you typed "
                      "with SAM 3.1 (Meta Model API, your Meta key), vote onto "
                      "the Gaussians, and split into separate splat objects")
    bl_options = {"REGISTER"}

    _workdir = ""
    _source_name = ""

    def invoke(self, context, event):
        settings = context.scene.muse_splat
        if settings.is_processing:
            self.report({"WARNING"}, "Segmentation already running (ESC cancels).")
            return {"CANCELLED"}
        source = _resolve_splat_object(context, settings)
        if source is None and settings.spz_path:
            try:
                source = _do_import_spz(context, settings)
            except RuntimeError as exc:
                settings.status = str(exc)
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
        if source is None:
            settings.status = ("No splat to segment: import an .spz or select "
                               "a PointCloud splat object first.")
            self.report({"ERROR"}, settings.status)
            return {"CANCELLED"}
        prompts = core.parse_prompts(settings.prompts)
        if not prompts:
            settings.status = ("Type at least one object to segment (e.g. "
                               "'sand, rock, shell'). Only what you type "
                               "is segmented.")
            self.report({"ERROR"}, settings.status)
            return {"CANCELLED"}
        api_key, key_source, base_url, _model = utils.api_settings(context)
        if not api_key:
            settings.status = ("No Meta API key. SAM 3.1 uses the same "
                               "META_API_KEY as Muse Image — add it to a "
                               ".env file or Addon Preferences first.")
            self.report({"ERROR"}, settings.status)
            return {"CANCELLED"}
        python, source_label = worker_python(context)
        if not python or not os.path.isfile(python):
            settings.status = ("No worker Python. Click Create Worker Env "
                               "(one-time, light install), or set Worker "
                               "Python in Preferences.")
            self.report({"ERROR"}, settings.status)
            return {"CANCELLED"}

        stamp = time.strftime("%Y%m%d_%H%M%S")
        slug = re.sub(r"[^a-z0-9]+", "_", source.name.lower()).strip("_")[:24]
        workdir = os.path.join(utils.splat_work_root(), f"{stamp}_{slug}")
        os.makedirs(workdir, exist_ok=True)
        settings.last_workdir = workdir
        settings.status = f"Exporting {len(source.data.points):,} Gaussians…"
        count = _export_splat(source, os.path.join(workdir, "input.npz"))
        self._workdir = workdir
        self._source_name = source.name

        command = [python, WORKER_SCRIPT,
                   "--input", os.path.join(workdir, "input.npz"),
                   "--out", os.path.join(workdir, "labels.npz"),
                   "--workdir", workdir,
                   "--prompts", settings.prompts,
                   "--base-url", base_url,
                   "--sam-model", sam_client.DEFAULT_SAM_MODEL,
                   "--views", str(int(settings.num_views)),
                   "--size", str(int(settings.resolution)),
                   "--sam-threshold", str(float(settings.sam_threshold)),
                   "--min-votes", str(int(settings.min_votes)),
                   "--min-cluster", str(int(settings.min_cluster))]
        env_file = _forward_env_file(context)
        if env_file:
            command += ["--env-file", env_file]
        env = dict(os.environ)
        env["META_API_KEY"] = api_key  # env only — never in argv or logs
        if env_file:
            env["MUSE_ENV_FILE"] = env_file
        log_path = os.path.join(workdir, "worker.log")
        settings.is_processing = True
        settings.status = (f"Segmenting {count:,} Gaussians with SAM 3.1 "
                           f"(Meta API, {source_label}; key: {key_source}); "
                           f"objects: {', '.join(prompts)}. ESC cancels.")

        def fn(job):
            with open(log_path, "w", encoding="utf-8") as log:
                proc = subprocess.Popen(command, stdout=log,
                                        stderr=subprocess.STDOUT, env=env)
                job["proc"] = proc
                while proc.poll() is None:
                    if job.get("cancel"):
                        proc.terminate()
                        raise RuntimeError("Cancelled")
                    try:
                        with open(os.path.join(workdir, "progress.json"),
                                  encoding="utf-8") as handle:
                            job["message"] = json.load(handle).get("message", "")
                    except (OSError, ValueError):
                        pass
                    time.sleep(0.3)
            if proc.returncode != 0:
                error = ""
                try:
                    with open(os.path.join(workdir, "report.json"),
                              encoding="utf-8") as handle:
                        error = json.load(handle).get("error", "")
                except (OSError, ValueError):
                    pass
                tail = "\n".join((error or _tail(log_path, 30)).splitlines()[-8:])
                raise RuntimeError(f"SAM 3.1 worker failed (exit {proc.returncode}):\n{tail}")
            with open(os.path.join(workdir, "report.json"),
                      encoding="utf-8") as handle:
                return json.load(handle)

        return self._begin_splat(context, f"splat-seg-{time.time_ns()}", fn)

    def _on_result(self, context, result):
        settings = context.scene.muse_splat
        source = bpy.data.objects.get(self._source_name)
        if source is None or source.type != "POINTCLOUD":
            settings.status = "Source splat object is gone; labels stay in the job folder."
            self.report({"ERROR"}, settings.status)
            return
        labels = np.load(os.path.join(self._workdir, "labels.npz"))
        instance_ids = np.asarray(labels["instance_ids"])
        confidence = (np.asarray(labels["confidence"])
                      if "confidence" in labels else None)
        if instance_ids.shape[0] != len(source.data.points):
            settings.status = ("Point count changed since export — re-run "
                               "Segment & Separate.")
            self.report({"ERROR"}, settings.status)
            return
        with open(os.path.join(self._workdir, "instances.json"),
                  encoding="utf-8") as handle:
            instances = json.load(handle)
        try:
            created = _separate_splat(context, source, instance_ids, confidence,
                                      instances, settings.keep_background)
        except RuntimeError as exc:
            settings.status = f"Error: {exc}"
            self.report({"ERROR"}, str(exc))
            return
        settings.last_summary = _summary(created, int(instance_ids.shape[0]))
        settings.status = settings.last_summary + f" Job folder: {self._workdir}"
        self.report({"INFO"}, settings.last_summary)


class MUSE_OT_splat_separate_again(bpy.types.Operator):
    bl_idname = "muse.splat_separate_again"
    bl_label = "Separate Again from Labels"
    bl_description = ("Re-split the active splat from its stored segment_id "
                      "attribute without re-running SAM 3.1")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.muse_splat
        source = _resolve_splat_object(context, settings)
        if source is None or "segment_id" not in source.data.attributes:
            self.report({"ERROR"}, "Active splat has no segment_id attribute — "
                                   "run Segment & Separate first.")
            return {"CANCELLED"}
        count = len(source.data.points)
        ids = np.empty(count, dtype=np.int32)
        source.data.attributes["segment_id"].data.foreach_get("value", ids)
        confidence = None
        if "segment_confidence" in source.data.attributes:
            confidence = np.empty(count, dtype=np.float32)
            source.data.attributes["segment_confidence"].data.foreach_get(
                "value", confidence)
        stored = source.get("splat_instances", "")
        instances = json.loads(stored) if stored else []
        known = {int(entry["id"]): entry for entry in instances}
        rebuilt = []
        for keep_id in sorted(int(v) for v in np.unique(ids)):
            entry = known.get(keep_id, {"id": keep_id, "label": 0, "prompt": ""})
            entry = dict(entry)
            entry["points"] = int((ids == keep_id).sum())
            rebuilt.append(entry)
        try:
            created = _separate_splat(context, source, ids, confidence, rebuilt,
                                      settings.keep_background)
        except RuntimeError as exc:
            settings.status = f"Error: {exc}"
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        settings.last_summary = _summary(created, count)
        settings.status = settings.last_summary
        self.report({"INFO"}, settings.last_summary)
        return {"FINISHED"}


class MUSE_OT_splat_open_workdir(bpy.types.Operator):
    bl_idname = "muse.splat_open_workdir"
    bl_label = "Open Job Folder"

    def execute(self, context):
        workdir = context.scene.muse_splat.last_workdir
        if workdir and os.path.isdir(workdir):
            bpy.ops.wm.path_open(filepath=workdir)
            return {"FINISHED"}
        self.report({"ERROR"}, "No job folder yet — run a segmentation first.")
        return {"CANCELLED"}


classes = (
    MUSE_OT_splat_import,
    MUSE_OT_splat_check_setup,
    MUSE_OT_splat_setup_worker,
    MUSE_OT_splat_segment,
    MUSE_OT_splat_separate_again,
    MUSE_OT_splat_open_workdir,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
