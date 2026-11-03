"""Gaussian-splat segmentation core (pure NumPy, no bpy, no torch).

Pipeline (training-free lifting, SAGD-style):

  1. Orbit cameras are placed on a Fibonacci sphere around the splat's
     robust (percentile-clipped) bounds, so floaters cannot blow up the
     framing.
  2. Each view is point-rasterised (nearest Gaussian wins, 2x2 splat) with
     a matching depth map. The same projection drives rendering and
     voting, so the two can never disagree about the camera.
  3. A segmenter (SAM 3.1 on the Meta Model API, in splat_worker.py)
     turns each view into a label image: 0 = background, k = k-th object
     the user typed. Only those objects are ever segmented.
  4. Every Gaussian votes in the views where it passes the depth test
     (projected depth <= rendered depth + tolerance). Majority wins.
  5. Same-concept Gaussians are split into separate objects by voxel
     connected components; tiny clusters fall back to background.

This module is imported both by Blender (colour conversion, prompt
parsing) and by the external worker (everything else), so it must stay
importable with nothing but NumPy available.
"""

from __future__ import annotations

import numpy as np

# 3DGS spherical-harmonics DC basis constant: rgb = 0.5 + SH_C0 * dc.
SH_C0 = 0.28209479177387814

def sh_to_rgb(dc: np.ndarray) -> np.ndarray:
    """Convert SH DC coefficients (..., 3) to clipped linear RGB."""
    return np.clip(0.5 + SH_C0 * np.asarray(dc, dtype=np.float32), 0.0, 1.0)


def parse_prompts(text: str) -> list[str]:
    """Split the objects field into clean, deduped prompts.

    Only what the user typed is returned — segmentation never adds
    concepts of its own.
    """
    prompts: list[str] = []
    for part in (text or "").split(","):
        phrase = " ".join(part.strip().lower().split())
        if phrase and phrase not in prompts:
            prompts.append(phrase)
    return prompts


def robust_frame(positions: np.ndarray, low: float = 1.0, high: float = 99.0):
    """Return (center, radius) from percentile-clipped bounds.

    Splat captures carry far-flung floaters (in the bundled sample 7% of
    points sit outside the subject), so min/max framing would shrink the
    subject to a speck. Percentile bounds frame the actual subject.
    """
    pos = np.asarray(positions, dtype=np.float32)
    lo = np.percentile(pos, low, axis=0)
    hi = np.percentile(pos, high, axis=0)
    center = ((lo + hi) * 0.5).astype(np.float32)
    clipped = pos[(pos >= lo).all(axis=1) & (pos <= hi).all(axis=1)]
    if clipped.size == 0:
        clipped = pos
    radius = float(np.max(np.linalg.norm(clipped - center, axis=1)))
    return center, max(radius, 1e-3)


def fibonacci_directions(count: int) -> np.ndarray:
    """Evenly spread unit directions on a sphere (golden-angle spiral)."""
    count = max(int(count), 1)
    i = np.arange(count, dtype=np.float64)
    z = 1.0 - 2.0 * (i + 0.5) / count
    r = np.sqrt(np.maximum(0.0, 1.0 - z * z))
    phi = i * 2.399963229728653  # golden angle
    dirs = np.stack([r * np.cos(phi), r * np.sin(phi), z], axis=1)
    return dirs.astype(np.float32)


def make_cameras(center: np.ndarray, radius: float, count: int,
                 fov_deg: float = 40.0) -> list[dict]:
    """Orbit cameras looking at `center`, framing a sphere of `radius`."""
    center = np.asarray(center, dtype=np.float32)
    dist = float(radius) / np.sin(np.radians(fov_deg) * 0.5) * 1.05
    cameras = []
    for direction in fibonacci_directions(count):
        eye = (center + direction * dist).astype(np.float32)
        forward = center - eye
        forward = (forward / np.linalg.norm(forward)).astype(np.float32)
        up_hint = np.array([0.0, 0.0, 1.0], dtype=np.float32)
        if abs(float(np.dot(forward, up_hint))) > 0.95:
            up_hint = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        right = np.cross(forward, up_hint)
        right = (right / np.linalg.norm(right)).astype(np.float32)
        up = np.cross(right, forward).astype(np.float32)
        cameras.append({
            "eye": eye, "right": right, "up": up, "forward": forward,
            "center": center.copy(), "distance": dist,
            "fov_deg": float(fov_deg),
        })
    return cameras


def project(positions: np.ndarray, camera: dict, width: int, height: int):
    """Project points into a view. Returns (u, v, depth, valid).

    u/v are integer pixel coordinates (clipped into range; check `valid`),
    depth is the forward distance, valid marks points inside the frustum
    and in front of the camera.
    """
    pos = np.asarray(positions, dtype=np.float32)
    rel = pos - camera["eye"]
    x = rel @ camera["right"]
    y = rel @ camera["up"]
    depth = rel @ camera["forward"]
    focal = (width * 0.5) / np.tan(np.radians(camera["fov_deg"]) * 0.5)
    with np.errstate(divide="ignore", invalid="ignore"):
        u_f = width * 0.5 + focal * x / depth
        v_f = height * 0.5 - focal * y / depth
    valid = (depth > 1e-6) & (u_f >= 0) & (u_f < width) & (v_f >= 0) & (v_f < height)
    u = np.clip(np.nan_to_num(u_f, nan=-1.0), -1, width).astype(np.int32)
    v = np.clip(np.nan_to_num(v_f, nan=-1.0), -1, height).astype(np.int32)
    return u, v, depth.astype(np.float32), valid


def render_from_proj(colors: np.ndarray, u: np.ndarray, v: np.ndarray,
                     depth: np.ndarray, valid: np.ndarray,
                     width: int, height: int,
                     background: float = 0.45, splat_2x2: bool = True):
    """Point-rasterise one view (nearest Gaussian wins) + depth map.

    Far-to-near painter order via a single descending sort: fully
    vectorised, ~2.3M points render in well under a second. A 2x2 splat
    footprint keeps the image solid at 1024px for SAM without a real
    Gaussian rasteriser (density does the rest).
    """
    colors = np.asarray(colors, dtype=np.float32)
    img = np.full((height * width, 3), float(background), dtype=np.float32)
    dmap = np.full(height * width, np.inf, dtype=np.float32)
    idx = np.flatnonzero(valid)
    if idx.size:
        order = idx[np.argsort(-depth[idx], kind="stable")]
        cols, deps = colors[order], depth[order]
        uu, vv = u[order], v[order]
        offsets = ((0, 0), (1, 0), (0, 1), (1, 1)) if splat_2x2 else ((0, 0),)
        for dx, dy in offsets:
            x, y = uu + dx, vv + dy
            inside = (x >= 0) & (x < width) & (y >= 0) & (y < height)
            flat = y[inside] * width + x[inside]
            img[flat] = cols[inside]
            dmap[flat] = deps[inside]
    image = np.clip(img.reshape(height, width, 3) * 255.0, 0, 255).astype(np.uint8)
    return image, dmap.reshape(height, width)


def build_label_image(instances, height: int, width: int) -> np.ndarray:
    """Paint per-concept instance masks into one label image.

    `instances` is a list of (prompt_index, score, bool_mask) with
    prompt_index 0-based. Higher scores paint last and win overlaps.
    Returns int16 labels: 0 = background, k = concept k (1-based).
    """
    label = np.zeros((height, width), dtype=np.int16)
    for prompt_index, _score, mask in sorted(instances, key=lambda t: t[1]):
        if mask is not None and mask.any():
            label[mask] = int(prompt_index) + 1
    return label


def vote_accumulate(votes: np.ndarray, visible: np.ndarray,
                    u: np.ndarray, v: np.ndarray, depth: np.ndarray,
                    valid: np.ndarray, label_image: np.ndarray,
                    depth_map: np.ndarray, tolerance: float) -> None:
    """Add one view's votes in place. votes is (N, K) int32.

    A Gaussian votes only where it is actually seen: its projected depth
    must sit within `tolerance` of the rendered (nearest) depth at its
    pixel. Occluded Gaussians behind the surface stay silent instead of
    stealing the surface's label.
    """
    idx = np.flatnonzero(valid)
    if idx.size == 0:
        return
    sampled = depth_map[v[idx], u[idx]]
    seen = depth[idx] <= sampled + tolerance
    idx = idx[seen]
    if idx.size == 0:
        return
    visible[idx] += 1
    labels = label_image[v[idx], u[idx]]
    labelled = labels > 0
    if labelled.any():
        np.add.at(votes, (idx[labelled], labels[labelled].astype(np.int64) - 1), 1)


def finalize_labels(votes: np.ndarray, visible: np.ndarray, min_votes: int):
    """Majority vote -> (semantic int32 0..K, confidence 0..1)."""
    count = int(votes.shape[0])
    if votes.shape[1] == 0:
        return np.zeros(count, dtype=np.int32), np.zeros(count, dtype=np.float32)
    best = votes.max(axis=1)
    semantic = (votes.argmax(axis=1) + 1).astype(np.int32)
    semantic[best < max(int(min_votes), 1)] = 0
    confidence = np.where(visible > 0, best / np.maximum(visible, 1), 0.0)
    return semantic, confidence.astype(np.float32)


def _components_for_label(points: np.ndarray, voxel_size: float) -> np.ndarray:
    """Connected-component id (0-based) per point via voxel union-find."""
    vox = np.floor(points / float(voxel_size)).astype(np.int64)
    uniq, inverse = np.unique(vox, axis=0, return_inverse=True)
    inverse = inverse.reshape(-1)
    shifted = uniq - uniq.min(axis=0)
    dims = shifted.max(axis=0) + 1
    keys = (shifted[:, 0] * dims[1] + shifted[:, 1]) * dims[2] + shifted[:, 2]
    index_of = {int(k): i for i, k in enumerate(keys)}
    parent = list(range(len(uniq)))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    offsets = [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
               for dz in (-1, 0, 1)
               if (dx, dy, dz) > (0, 0, 0)]
    mult = (int(dims[1] * dims[2]), int(dims[2]), 1)
    for i, key in enumerate(keys):
        base = int(key)
        for dx, dy, dz in offsets:
            other = index_of.get(base + dx * mult[0] + dy * mult[1] + dz * mult[2])
            if other is not None:
                ra, rb = find(i), find(other)
                if ra != rb:
                    parent[rb] = ra
    roots = np.array([find(i) for i in range(len(uniq))], dtype=np.int64)
    _uniq_roots, comp = np.unique(roots, return_inverse=True)
    return comp[inverse].astype(np.int32)


def split_instances(positions: np.ndarray, semantic: np.ndarray,
                    voxel_size: float, min_points: int):
    """Split each concept's Gaussians into spatially separate instances.

    Returns (instance_ids int32, info) where instance_ids is 0 for
    background/noise and 1..M for kept instances, and info[m-1] is
    {"id": m, "label": concept index 1..K, "points": count}.
    """
    pos = np.asarray(positions, dtype=np.float32)
    sem = np.asarray(semantic)
    instance_ids = np.zeros(pos.shape[0], dtype=np.int32)
    info: list[dict] = []
    next_id = 1
    for label in sorted(int(v) for v in np.unique(sem) if v > 0):
        members = np.flatnonzero(sem == label)
        if members.size == 0:
            continue
        comp = _components_for_label(pos[members], voxel_size)
        counts = np.bincount(comp)
        for comp_id, size in enumerate(counts):
            if size < max(int(min_points), 1):
                continue  # speckle: falls back to background, never deleted
            instance_ids[members[comp == comp_id]] = next_id
            info.append({"id": next_id, "label": label, "points": int(size)})
            next_id += 1
    return instance_ids, info
