"""Modal cloud-render client (pure stdlib, no bpy imports).

Implements the pattern from Modal's Blender example
(https://modal.com/docs/examples/blender_video):

  * a container image with Blender installed as the `bpy` package,
  * a `render` function that renders one frame of an uploaded .blend file
    (GPU-accelerated on Cycles when requested),
  * `render.map` / `render.starmap` to render an animation in parallel,
  * a `combine` function (ffmpeg) that stitches frames into an MP4.

This module only *generates* that Modal app to disk and runs it with the
Modal CLI (`modal run ...`). The .blend bytes are uploaded by the generated
app's local entrypoint; the rendered PNG/MP4 bytes are written back next to
the user's .blend file by the Blender operator that calls this module.

Credentials are resolved (in order) from:
  1. explicit values (Addon Preferences override),
  2. environment variables MODAL_TOKEN_ID / MODAL_TOKEN_SECRET,
  3. a `.env` file (addon folder, .blend folder, cwd, home, or a custom path).

Tokens are passed to the Modal CLI through the child process environment
only — they are never written into the generated app, the command line, or
any output file. This module must stay importable outside Blender.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field

from . import api_client

MODAL_TOKEN_ID_NAME = "MODAL_TOKEN_ID"
MODAL_TOKEN_SECRET_NAME = "MODAL_TOKEN_SECRET"
DEFAULT_APP_NAME = "muse-blender-cloud-render"
DEFAULT_GPU = "L40S"
GPU_TYPES = ("L40S", "L4", "A10G", "T4", "A100", "H100")
BPY_VERSION = "4.5.0"


class ModalError(RuntimeError):
    """Raised for missing credentials, a missing CLI, or a failed run."""


@dataclass
class ModalCredentials:
    token_id: str = ""
    token_secret: str = ""
    source: str = "not found"

    @property
    def ok(self) -> bool:
        return bool(self.token_id and self.token_secret)


@dataclass
class CloudRenderResult:
    output_dir: str
    still_path: str = ""
    video_path: str = ""
    frame_paths: list[str] = field(default_factory=list)
    log_tail: str = ""


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def resolve_modal_credentials(
    explicit_id: str = "",
    explicit_secret: str = "",
    extra_dotenv_paths: list[str] | None = None,
) -> ModalCredentials:
    """Return ModalCredentials. Never raises; `ok` is False when incomplete."""
    token_id = (explicit_id or "").strip()
    token_secret = (explicit_secret or "").strip()
    if token_id and token_secret:
        return ModalCredentials(token_id, token_secret, "Addon Preferences")
    if token_id or token_secret:
        # One half in Preferences, the other half may come from env / .env.
        source = "Addon Preferences (partial)"
    else:
        source = ""

    env_id = os.environ.get(MODAL_TOKEN_ID_NAME, "").strip()
    env_secret = os.environ.get(MODAL_TOKEN_SECRET_NAME, "").strip()
    if (env_id or env_secret) and not token_id and not token_secret:
        token_id, token_secret = env_id, env_secret
        source = f"environment variables {MODAL_TOKEN_ID_NAME}/{MODAL_TOKEN_SECRET_NAME}"
    elif env_id and not token_id:
        token_id, source = env_id, f"environment variable {MODAL_TOKEN_ID_NAME}"
    elif env_secret and not token_secret:
        token_secret, source = env_secret, f"environment variable {MODAL_TOKEN_SECRET_NAME}"

    if not (token_id and token_secret):
        for path in api_client.dotenv_candidates(extra_dotenv_paths):
            values = api_client.parse_dotenv(path)
            found_id = values.get(MODAL_TOKEN_ID_NAME, "").strip()
            found_secret = values.get(MODAL_TOKEN_SECRET_NAME, "").strip()
            if found_id and not token_id:
                token_id, source = found_id, f"{MODAL_TOKEN_ID_NAME} in {path}"
            if found_secret and not token_secret:
                token_secret = found_secret
                if not source:
                    source = f"{MODAL_TOKEN_SECRET_NAME} in {path}"
            if token_id and token_secret:
                break

    if not source:
        source = ("not found (set MODAL_TOKEN_ID + MODAL_TOKEN_SECRET in a "
                  ".env file or in Addon Preferences)")
    return ModalCredentials(token_id, token_secret, source)


def find_modal_cli(explicit_path: str = "") -> str:
    """Locate the `modal` CLI, or '' when it is not installed."""
    if explicit_path and explicit_path.strip():
        candidate = os.path.expanduser(explicit_path.strip())
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    return shutil.which("modal") or ""


# ---------------------------------------------------------------------------
# Generated Modal app (the https://modal.com/docs/examples/blender_video
# pattern, adapted to respect the saved scene's camera/render settings)
# ---------------------------------------------------------------------------

def build_modal_app_source(app_name: str = DEFAULT_APP_NAME,
                           gpu: str = DEFAULT_GPU,
                           use_gpu: bool = True,
                           max_containers: int = 10) -> str:
    """Return the source of the Modal app that renders .blend frames."""
    app_name = (app_name or DEFAULT_APP_NAME).strip() or DEFAULT_APP_NAME
    gpu = gpu if gpu in GPU_TYPES else DEFAULT_GPU
    gpu_arg = f'"{gpu}"' if use_gpu else "None"
    max_containers = max(1, min(int(max_containers or 10), 100))
    return f'''"""Generated by Muse Harness (Blender addon) — do not edit.

Pattern: https://modal.com/docs/examples/blender_video
Renders the saved scene camera. Scene render settings (resolution, engine,
samples, frame range) are taken from the .blend file as saved; only the
Cycles device is switched to GPU (with CPU fallback) when requested.
"""

from pathlib import Path

import modal

app = modal.App({app_name!r})

rendering_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("xorg", "libxkbcommon0")  # X11 (Unix GUI) dependencies
    .uv_pip_install("bpy=={BPY_VERSION}")  # Blender as a Python package
)

combination_image = modal.Image.debian_slim(python_version="3.11").apt_install("ffmpeg")

WITH_GPU = {bool(use_gpu)!r}


def _configure_rendering(ctx):
    scene = ctx.scene
    if scene.render.engine not in ("CYCLES", "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        return
    if scene.render.engine != "CYCLES":
        return  # Eevee: keep the scene's own device settings.
    cycles_addon = ctx.preferences.addons.get("cycles")
    if cycles_addon is None:
        return
    prefs = cycles_addon.preferences
    if WITH_GPU:
        try:
            prefs.compute_device_type = "CUDA"
            scene.cycles.device = "GPU"
            prefs.get_devices()
            for device in prefs.devices:
                device.use = True
        except Exception:  # noqa: BLE001 - fall back to CPU below
            scene.cycles.device = "CPU"
    else:
        scene.cycles.device = "CPU"
    for device in getattr(prefs, "devices", []):
        try:
            print(f"device: {{device.name}} type={{device.type}} use={{device.use}}")
        except Exception:  # noqa: BLE001
            pass


@app.function(
    gpu={gpu_arg},
    max_containers={max_containers},
    image=rendering_image,
    timeout=60 * 60,
)
def render(blend_file: bytes, frame_number: int = 1) -> bytes:
    """Render one frame of a Blender file (scene camera) as PNG bytes."""
    import bpy

    input_path = "/tmp/input.blend"
    output_path = f"/tmp/output-{{frame_number:05d}}.png"
    Path(input_path).write_bytes(blend_file)
    bpy.ops.wm.open_mainfile(filepath=input_path)
    scene = bpy.context.scene
    if scene.camera is None:
        raise RuntimeError("Scene has no active camera. Set one before cloud rendering.")
    scene.frame_set(frame_number)
    scene.render.filepath = output_path
    scene.render.image_settings.file_format = "PNG"
    _configure_rendering(bpy.context)
    bpy.ops.render.render(write_still=True)
    return Path(output_path).read_bytes()


@app.function(image=combination_image, timeout=60 * 30)
def combine(frames_bytes: list[bytes], fps: int = 24) -> bytes:
    """Stitch rendered frames into an MP4 (ffmpeg, from the Modal example)."""
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        for i, frame_bytes in enumerate(frames_bytes):
            (Path(tmpdir) / f"frame_{{i:05d}}.png").write_bytes(frame_bytes)
        out_path = Path(tmpdir) / "output.mp4"
        subprocess.run(
            f"ffmpeg -y -framerate {{fps}} -pattern_type glob -i '{{tmpdir}}/*.png' "
            f"-c:v libx264 -pix_fmt yuv420p {{out_path}}",
            shell=True, check=True,
        )
        return out_path.read_bytes()


@app.local_entrypoint()
def main(blend_path: str, output_dir: str, mode: str = "still",
         frame: int = 1, frame_start: int = 1, frame_end: int = 1,
         frame_step: int = 1, fps: int = 24):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    blend_bytes = Path(blend_path).read_bytes()
    if mode == "animation":
        frames = list(range(frame_start, frame_end + 1, max(1, frame_step)))
        args = [(blend_bytes, f) for f in frames]
        images = list(render.starmap(args))
        for f, image in zip(frames, images):
            path = out / f"cloud_frame_{{f:05d}}.png"
            path.write_bytes(image)
            print(f"Frame saved to {{path}}")
        video_path = out / "cloud_render.mp4"
        video_path.write_bytes(combine.remote(images, fps))
        print(f"Video saved to {{video_path}}")
    else:
        image = render.remote(blend_bytes, frame)
        path = out / f"cloud_frame_{{frame:05d}}.png"
        path.write_bytes(image)
        print(f"Frame saved to {{path}}")
'''


def write_modal_app(directory: str, app_name: str = DEFAULT_APP_NAME,
                    gpu: str = DEFAULT_GPU, use_gpu: bool = True,
                    max_containers: int = 10) -> str:
    """Write the generated Modal app into `directory`; return its path."""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "muse_modal_render.py")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(build_modal_app_source(app_name, gpu, use_gpu, max_containers))
    return path


# ---------------------------------------------------------------------------
# Running the app with the Modal CLI
# ---------------------------------------------------------------------------

def build_command(modal_cli: str, app_path: str, blend_path: str,
                  output_dir: str, mode: str = "still", frame: int = 1,
                  frame_start: int = 1, frame_end: int = 1,
                  frame_step: int = 1, fps: int = 24) -> list[str]:
    """Build the `modal run` command. Tokens are never part of it."""
    return [
        modal_cli, "run", app_path,
        "--blend-path", blend_path,
        "--output-dir", output_dir,
        "--mode", mode,
        "--frame", str(int(frame)),
        "--frame-start", str(int(frame_start)),
        "--frame-end", str(int(frame_end)),
        "--frame-step", str(max(1, int(frame_step))),
        "--fps", str(max(1, int(fps))),
    ]


def run_cloud_render(modal_cli: str, app_path: str, blend_path: str,
                     output_dir: str, credentials: ModalCredentials,
                     mode: str = "still", frame: int = 1,
                     frame_start: int = 1, frame_end: int = 1,
                     frame_step: int = 1, fps: int = 24,
                     timeout: int = 3600) -> CloudRenderResult:
    """Run `modal run` and collect the files it writes into `output_dir`."""
    if not credentials.ok:
        raise ModalError(
            "No Modal tokens: set MODAL_TOKEN_ID + MODAL_TOKEN_SECRET in a "
            ".env file or in Edit > Preferences > Add-ons > Muse Harness.")
    if not modal_cli:
        raise ModalError(
            "Modal CLI not found. Install it with `pip install modal` "
            "(or set Modal CLI Path in Addon Preferences), then run "
            "`modal token new` or paste your tokens in Preferences.")
    if not os.path.isfile(blend_path):
        raise ModalError(f"Blend file to upload does not exist: {blend_path}")
    os.makedirs(output_dir, exist_ok=True)

    env = dict(os.environ)
    env[MODAL_TOKEN_ID_NAME] = credentials.token_id
    env[MODAL_TOKEN_SECRET_NAME] = credentials.token_secret
    command = build_command(modal_cli, app_path, blend_path, output_dir,
                            mode=mode, frame=frame, frame_start=frame_start,
                            frame_end=frame_end, frame_step=frame_step, fps=fps)
    try:
        proc = subprocess.run(command, env=env, capture_output=True, text=True,
                              timeout=max(60, int(timeout)))
    except subprocess.TimeoutExpired as exc:
        raise ModalError(f"Modal render timed out after {timeout}s.") from exc
    except OSError as exc:
        raise ModalError(f"Could not launch the Modal CLI ({modal_cli}): {exc}") from exc
    log = "\n".join(part for part in (proc.stdout or "", proc.stderr or "") if part)
    if proc.returncode != 0:
        tail = "\n".join(log.splitlines()[-20:])
        raise ModalError(f"Modal run failed (exit {proc.returncode}):\n{tail}")

    result = CloudRenderResult(output_dir=output_dir, log_tail="\n".join(log.splitlines()[-20:]))
    if mode == "animation":
        result.frame_paths = sorted(
            os.path.join(output_dir, name) for name in os.listdir(output_dir)
            if name.startswith("cloud_frame_") and name.endswith(".png"))
        video = os.path.join(output_dir, "cloud_render.mp4")
        if os.path.isfile(video):
            result.video_path = video
        if not result.frame_paths:
            raise ModalError(f"Modal finished but no frames landed in {output_dir}:\n{result.log_tail}")
    else:
        still = os.path.join(output_dir, f"cloud_frame_{int(frame):05d}.png")
        if not os.path.isfile(still):
            raise ModalError(f"Modal finished but {still} was not written:\n{result.log_tail}")
        result.still_path = still
        result.frame_paths = [still]
    return result
