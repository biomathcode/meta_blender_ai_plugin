"""Tests for muse_ai_texture/splat_core.py (pure NumPy, no Blender).

Run with any Python that has NumPy:
    .venv-splat/bin/python tests/test_splat_core.py
    python3 tests/test_splat_core.py

Covers the training-free lifting pipeline end to end with a colour-rule
stand-in for SAM: orbit cameras -> point renders -> label images ->
depth-tested majority vote -> per-concept instance splitting. The SAM 3
worker itself (splat_worker.py) feeds real masks through the same
build_label_image/vote path.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "muse_ai_texture"))

import numpy as np  # noqa: E402

import splat_core as core  # noqa: E402


def _ball(rng, center, radius, count, color):
    dirs = rng.normal(size=(count, 3))
    dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
    pos = np.array(center, dtype=np.float32) + (dirs * radius).astype(np.float32)
    col = np.tile(np.array(color, dtype=np.float32), (count, 1))
    return pos, col


def test_sh_to_rgb():
    dc = np.array([[0.0, 0.0, 0.0], [10.0, -10.0, 1.0]], dtype=np.float32)
    rgb = core.sh_to_rgb(dc)
    assert np.allclose(rgb[0], 0.5)
    assert rgb[1, 0] == 1.0 and rgb[1, 1] == 0.0  # clipped both ends


def test_parse_prompts():
    assert core.parse_prompts(" Sand, rock ,SAND, , red  car ") == [
        "sand", "rock", "red car"]
    assert core.parse_prompts("") == []
    # Only what the user typed comes back — no built-in vocabulary is added.
    assert core.parse_prompts("sand") == ["sand"]


def test_voting_and_splitting():
    rng = np.random.default_rng(7)
    pa, ca = _ball(rng, (-1.2, 0, 0.6), 0.55, 30000, (0.9, 0.2, 0.2))
    pb, cb = _ball(rng, (1.2, 0, 0.6), 0.55, 30000, (0.9, 0.25, 0.2))
    gx, gy = np.meshgrid(np.linspace(-2.5, 2.5, 160),
                         np.linspace(-2.5, 2.5, 160))
    ground = np.stack([gx.ravel(), gy.ravel(),
                       np.zeros(gx.size)], axis=1).astype(np.float32)
    gcol = np.tile(np.array([0.85, 0.75, 0.4], dtype=np.float32),
                   (ground.shape[0], 1))
    pos = np.concatenate([pa, pb, ground])
    col = np.concatenate([ca, cb, gcol])
    truth_ball = np.concatenate(
        [np.ones(len(pa) + len(pb), bool), np.zeros(len(ground), bool)])

    center, radius = core.robust_frame(pos)
    assert radius < 4.0  # percentile framing ignores outliers by design
    cameras = core.make_cameras(center, radius, 12, 40.0)
    width = height = 512
    votes = np.zeros((len(pos), 2), dtype=np.int32)
    visible = np.zeros(len(pos), dtype=np.int32)
    tolerance = 0.03 * radius
    for cam in cameras:
        u, v, depth, valid = core.project(pos, cam, width, height)
        img, dmap = core.render_from_proj(col, u, v, depth, valid,
                                          width, height)
        r, g = img[..., 0].astype(int), img[..., 1].astype(int)
        label_img = core.build_label_image(
            [(0, 0.9, (r > 150) & (g < 120)),
             (1, 0.8, (r > 150) & (g >= 120))], height, width)
        core.vote_accumulate(votes, visible, u, v, depth, valid,
                             label_img, dmap, tolerance)

    semantic, _conf = core.finalize_labels(votes, visible, min_votes=2)
    assert float((semantic[truth_ball] == 1).mean()) > 0.85
    assert float((semantic[~truth_ball] == 2).mean()) > 0.85

    instance_ids, info = core.split_instances(
        pos, semantic, voxel_size=radius / 100.0, min_points=500)
    balls = [entry for entry in info if entry["label"] == 1]
    grounds = [entry for entry in info if entry["label"] == 2]
    assert len(balls) == 2, info  # same concept, two separate objects
    assert len(grounds) == 1, info
    assert int((instance_ids > 0).sum()) == sum(e["points"] for e in info)
    assert instance_ids.shape[0] == len(pos)  # nothing lost


if __name__ == "__main__":
    test_sh_to_rgb()
    test_parse_prompts()
    test_voting_and_splitting()
    print("test_splat_core: OK")
