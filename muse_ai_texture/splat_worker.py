#!/usr/bin/env python3
"""SAM 3.1 splat-segmentation worker — runs OUTSIDE Blender, never inside it.

The worker renders orbit views of the splat and votes 2D masks back onto
the Gaussians locally (pure NumPy), but segmentation itself runs on the
Meta Model API: SAM 3.1 (`sam-3.1`) via POST /v1/responses, authenticated
with the addon's existing Meta key (META_API_KEY — the same key Blender
already asks for). No Hugging Face token, no local weights, no GPU: the
worker only needs numpy, pillow and meta-sam-parser.

File contract with the Blender operator:

  in : input.npz  {positions (N,3) f32, colors (N,3) f32, opacity (N,) f32}
  out: labels.npz {instance_ids (N,) i32, semantic (N,) i32,
                   confidence (N,) f32}
       instances.json [{id, label, prompt, points}]  (id 0 = background)
       report.json, progress.json, views/view_XX.png, views/label_XX.png

Usage:
  python3 splat_worker.py --check
  python3 splat_worker.py --input input.npz --out labels.npz \
      --workdir job_dir --prompts "sand, rock, shell"

Only the objects typed in --prompts are segmented — one Meta API request
per concept per view (SAM 3.1 takes one noun phrase per request). There
is no automatic / everything segmentation.

SAM 3.1 always runs on the Meta Model API (same META_API_KEY as Muse
Image). Modal / local GPU is never used for segmentation; the legacy
--backend / --modal-gpu flags are accepted for compatibility and ignored.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

import api_client  # noqa: E402
import sam_client  # noqa: E402
import splat_core as core  # noqa: E402

LABEL_COLORS = np.array([
    [0, 0, 0], [230, 25, 75], [60, 180, 75], [255, 225, 25],
    [0, 130, 200], [245, 130, 48], [145, 30, 180], [70, 240, 240],
    [240, 50, 230], [210, 245, 60], [250, 190, 212], [0, 128, 128],
], dtype=np.uint8)


def _progress(workdir: str, **fields) -> None:
    try:
        with open(os.path.join(workdir, "progress.json"), "w", encoding="utf-8") as fh:
            json.dump(fields, fh)
    except OSError:
        pass
    print(json.dumps(fields), flush=True)


def _meta_api_key(workdir: str = "", env_file: str = "") -> str:
    """Resolve the Meta key exactly like Blender does (env, then .env files).

    The Blender operator forwards the resolved key as META_API_KEY, but the
    worker must not depend on that alone: a key that is only in a .env file
    (addon folder, project root, .blend folder, Preferences .env File, or
    the repo-root .env) is "already setup" for Muse Image yet invisible to
    a bare env-var lookup. Search the same places api_client does, plus the
    project root (parent of this addon folder) and the job workdir tree.
    """
    key, _source = _meta_api_key_with_source(workdir, env_file)
    return key


def _meta_api_key_with_source(workdir: str = "", env_file: str = "") -> tuple[str, str]:
    for name in api_client.ENV_VAR_NAMES:
        value = os.environ.get(name, "").strip()
        if value:
            return value, f"environment variable {name}"
    extra: list[str] = []
    for candidate in (env_file, os.environ.get("MUSE_ENV_FILE", "")):
        if candidate:
            extra.append(candidate)
    # Project root in the repo layout: <root>/muse_ai_texture/splat_worker.py
    # -> <root>/.env. In the installed layout this is addons/.env (harmless).
    addon_dir = os.path.dirname(os.path.abspath(__file__))
    extra.append(os.path.join(os.path.dirname(addon_dir), ".env"))
    # Job workdir may sit under <blend dir>/muse_splat/<job>/; walk up so a
    # .env next to the .blend (or in the project root above it) is found.
    current = os.path.abspath(workdir) if workdir else ""
    for _ in range(4):
        if not current:
            break
        extra.append(os.path.join(current, ".env"))
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return api_client.resolve_api_key("", extra)


# ---------------------------------------------------------------------------
# Segmenter: (image uint8 HxWx3, prompts) -> [(prompt_idx, score, mask)]
# ---------------------------------------------------------------------------

class Sam3MetaAPI:
    """SAM 3.1 on the Meta Model API, one request per concept per view."""

    def __init__(self, api_key: str, base_url: str = sam_client.DEFAULT_BASE_URL,
                 model: str = sam_client.DEFAULT_SAM_MODEL,
                 threshold: float = 0.5, timeout: int = 180):
        if not api_key:
            raise RuntimeError(
                "No Meta API key for SAM 3.1. It uses the same META_API_KEY "
                "as Muse Image — checked environment variables and .env "
                "files (addon folder, project root, .blend folder, "
                "Preferences .env File, --env-file). Add the key to one of "
                "those, or paste it in Addon Preferences.")
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.threshold = float(threshold)
        self.timeout = int(timeout)

    def segment(self, image: np.ndarray, prompts: list[str]):
        from PIL import Image

        height, width = image.shape[:2]
        buffer = io.BytesIO()
        Image.fromarray(image).save(buffer, format="PNG")
        png = buffer.getvalue()
        found = []
        for index, phrase in enumerate(prompts):
            hits = sam_client.segment_image_png(
                png, phrase, self.api_key, height, width,
                threshold=self.threshold, base_url=self.base_url,
                model=self.model, timeout=self.timeout)
            for score, mask in hits:
                found.append((index, float(score), mask))
        return found


# ---------------------------------------------------------------------------
# Checks + main run
# ---------------------------------------------------------------------------

def run_check(workdir: str = "", env_file: str = "") -> dict:
    info: dict = {"python": sys.executable, "numpy": np.__version__,
                  "sam_model": sam_client.DEFAULT_SAM_MODEL}
    try:
        import PIL
        info["pillow"] = PIL.__version__
    except Exception:  # noqa: BLE001
        info["pillow"] = ""
    try:
        import meta_sam_parser  # noqa: F401
        info["meta_sam_parser"] = True
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        info["meta_sam_parser"] = False
        info["meta_sam_parser_error"] = str(exc)
    _key, _source = _meta_api_key_with_source(workdir, env_file)
    info["meta_key"] = bool(_key)
    info["meta_key_source"] = _source if _key else ""
    info["ready"] = bool(info.get("pillow") and info.get("meta_sam_parser"))
    info["ready_api"] = bool(info["ready"] and info["meta_key"])
    return info


def _save_png(path: str, array: np.ndarray) -> None:
    from PIL import Image
    Image.fromarray(array).save(path)


def run(args: argparse.Namespace) -> dict:
    workdir = args.workdir
    os.makedirs(os.path.join(workdir, "views"), exist_ok=True)
    _progress(workdir, stage="load", message="Loading splat points…")
    data = np.load(args.input)
    positions = np.asarray(data["positions"], dtype=np.float32)
    colors = np.asarray(data["colors"], dtype=np.float32)
    count = int(positions.shape[0])
    prompts = core.parse_prompts(args.prompts)
    if not prompts:
        raise ValueError("No objects given. Type at least one object to "
                         "segment (e.g. 'sand, rock, shell'). Only the "
                         "objects you type are segmented.")
    center, radius = core.robust_frame(positions)
    cameras = core.make_cameras(center, radius, args.views, fov_deg=args.fov)
    width = height = int(args.size)
    tolerance = float(args.depth_tol) * radius
    voxel = float(args.voxel) if args.voxel > 0 else radius / 100.0
    votes = np.zeros((count, len(prompts)), dtype=np.int32)
    visible = np.zeros(count, dtype=np.int32)
    _progress(workdir, stage="views", message=f"{count:,} points, "
              f"{len(cameras)} views, {len(prompts)} objects: {', '.join(prompts)}")

    def render_view(index: int):
        cam = cameras[index]
        proj = core.project(positions, cam, width, height)
        image, depth_map = core.render_from_proj(colors, *proj, width, height)
        _save_png(os.path.join(workdir, "views", f"view_{index:02d}.png"), image)
        return proj, image, depth_map

    # SAM 3.1 is Meta-API-only: --backend local/modal and --modal-gpu are
    # legacy caller flags. Never launch Modal or local weights — warn and
    # fall through to the Meta Model API path below.
    _requested_backend = getattr(args, "backend", "meta-api") or "meta-api"
    _modal_gpu = getattr(args, "modal_gpu", "") or ""
    if _requested_backend != "meta-api" or _modal_gpu:
        _progress(workdir, stage="backend",
                  message=f"Ignoring --backend {_requested_backend}"
                          + (f" --modal-gpu {_modal_gpu}" if _modal_gpu else "")
                          + " — SAM 3.1 runs on the Meta Model API, not Modal GPU.")
    if _requested_backend == "none":
        args.segmenter = "none"

    if args.segmenter == "none":
        for i in range(len(cameras)):
            proj, _image, depth_map = render_view(i)
            label_image = np.zeros((height, width), dtype=np.int16)
            colour = LABEL_COLORS[np.clip(label_image, 0, len(LABEL_COLORS) - 1)]
            _save_png(os.path.join(workdir, "views", f"label_{i:02d}.png"), colour)
            core.vote_accumulate(votes, visible, proj[0], proj[1], proj[2],
                                 proj[3], label_image, depth_map, tolerance)
            _progress(workdir, stage="vote", view=i + 1, total=len(cameras),
                      message=f"View {i + 1}/{len(cameras)} voted")
    else:
        _api_key, _key_source = _meta_api_key_with_source(
            workdir, getattr(args, "env_file", "") or "")
        _progress(workdir, stage="sam3-api",
                  message=f"Segmenting with SAM 3.1 ({args.sam_model}) on the "
                          f"Meta Model API… (key: {_key_source})")
        segmenter = Sam3MetaAPI(_api_key, base_url=args.base_url,
                                model=args.sam_model,
                                threshold=args.sam_threshold,
                                timeout=args.timeout)
        for i in range(len(cameras)):
            proj, image, depth_map = render_view(i)
            found = segmenter.segment(image, prompts)
            label_image = core.build_label_image(found, height, width)
            colour = LABEL_COLORS[np.clip(label_image, 0, len(LABEL_COLORS) - 1)]
            _save_png(os.path.join(workdir, "views", f"label_{i:02d}.png"), colour)
            core.vote_accumulate(votes, visible, proj[0], proj[1], proj[2],
                                 proj[3], label_image, depth_map, tolerance)
            _progress(workdir, stage="vote", view=i + 1, total=len(cameras),
                      message=f"View {i + 1}/{len(cameras)}: "
                              f"{len(found)} masks (SAM 3.1 API)")

    _progress(workdir, stage="split", message="Splitting into separate objects…")
    semantic, confidence = core.finalize_labels(votes, visible, args.min_votes)
    instance_ids, info = core.split_instances(positions, semantic, voxel,
                                              args.min_cluster)
    instances = [{"id": 0, "label": 0, "prompt": "",
                  "points": int((instance_ids == 0).sum())}]
    for entry in info:
        instances.append({"id": entry["id"], "label": entry["label"],
                          "prompt": prompts[entry["label"] - 1],
                          "points": entry["points"]})
    np.savez(args.out, instance_ids=instance_ids, semantic=semantic,
             confidence=confidence)
    with open(os.path.join(workdir, "instances.json"), "w", encoding="utf-8") as fh:
        json.dump(instances, fh, indent=1)
    report = {
        "points": count, "prompts": prompts, "views": len(cameras),
        "backend": "meta-api" if args.segmenter != "none" else "none",
        "sam_model": args.sam_model,
        "radius": radius, "voxel": voxel, "instances": instances,
        "labelled_points": int((instance_ids > 0).sum()),
    }
    with open(os.path.join(workdir, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    _progress(workdir, stage="done", message=f"Done: {len(info)} objects, "
              f"{report['labelled_points']:,} labelled points")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="Print worker capability JSON and exit")
    parser.add_argument("--input", default="")
    parser.add_argument("--out", default="")
    parser.add_argument("--workdir", default=".")
    parser.add_argument("--prompts", default="")
    parser.add_argument("--segmenter", choices=("sam3", "none"), default="sam3",
                        help="Internal: 'none' skips SAM (pipeline plumbing test)")
    parser.add_argument("--base-url", default=sam_client.DEFAULT_BASE_URL)
    parser.add_argument("--sam-model", default=sam_client.DEFAULT_SAM_MODEL)
    parser.add_argument("--timeout", type=int, default=180,
                        help="Per-request Meta API timeout in seconds")
    parser.add_argument("--views", type=int, default=16)
    parser.add_argument("--size", type=int, default=1024)
    parser.add_argument("--fov", type=float, default=40.0)
    parser.add_argument("--sam-threshold", type=float, default=0.5)
    parser.add_argument("--min-votes", type=int, default=2)
    parser.add_argument("--depth-tol", type=float, default=0.025,
                        help="Occlusion tolerance as a fraction of scene radius")
    parser.add_argument("--voxel", type=float, default=0.0,
                        help="Instance-split voxel size (0 = radius/100)")
    parser.add_argument("--min-cluster", type=int, default=800)
    # Legacy compatibility: some callers still pass --backend local/modal
    # and --modal-gpu L40S. SAM 3.1 segmentation is Meta-Model-API-only, so
    # these are accepted and ignored (see run()) — never routed to Modal.
    parser.add_argument("--backend", default="meta-api",
                        choices=("meta-api", "api", "local", "modal", "none"),
                        help="Ignored except 'none' via --segmenter: SAM 3.1 "
                             "always runs on the Meta Model API")
    parser.add_argument("--modal-gpu", default="", dest="modal_gpu",
                        help="Ignored: retained for caller compatibility; "
                             "Modal GPU is not used for SAM segmentation")
    parser.add_argument("--modal-app", default="", dest="modal_app",
                        help="Ignored: Modal app name (not used for SAM)")
    parser.add_argument("--gpu", default="", dest="modal_gpu",
                        help="Ignored alias for --modal-gpu")
    parser.add_argument("--env-file", default="", dest="env_file",
                        help="Explicit .env file holding META_API_KEY "
                             "(forwarded from Addon Preferences by the operator)")
    args, _unknown = parser.parse_known_args()
    if _unknown:
        # Tolerate any other legacy --modal-*/--backend-style flags rather
        # than crashing with exit 2; SAM stays on the Meta API regardless.
        print(f"splat_worker: ignoring unrecognized arguments: {_unknown}",
              flush=True)

    if args.check:
        print(json.dumps(run_check(args.workdir, args.env_file)))
        return 0
    try:
        run(args)
    except Exception:  # noqa: BLE001 - full detail goes to the job log/report
        traceback.print_exc()
        try:
            with open(os.path.join(args.workdir, "report.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"error": traceback.format_exc()}, fh)
            _progress(args.workdir, stage="error",
                      message=traceback.format_exc().splitlines()[-1])
        except Exception:  # noqa: BLE001
            pass
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
