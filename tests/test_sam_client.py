"""Tests for muse_ai_texture/sam_client.py mask decoding (no network).

Run with the worker env (needs numpy + meta-sam-parser):
    .venv-splat/bin/python tests/test_sam_client.py

Feeds sam_client.parse_masks the exact SAM 3.1 wire text the Meta Model
API emits and checks placement (box bounds), raster size and the
confidence threshold — the worker's voting path consumes these masks.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "muse_ai_texture"))

import numpy as np  # noqa: E402

import sam_client  # noqa: E402

# Two objects on a 320x334 frame (Meta docs example payloads).
WIRE = (
    "<0f>0<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334|>"
    "<|mask;x=0;y=0;data=27,60,~!!!!M!0c[0o91w?q1!pIH4pPRVp2B3'7`e.ioeAf6-k/#Xd8%dX9x(|>"
    ",1<|box;x1=155;y1=228;x2=202;y2=254;w=320;h=334|>"
    "<|mask;x=0;y=0;data=27,48,~!!!!J!0c[q=Pj_zs=*4C4(/./x#:/`S_GnD`=o3?X{emCgO$y@|>\n"
)


def test_parse_masks_placement():
    found = sam_client.parse_masks(WIRE, height=334, width=320, threshold=0.0)
    assert len(found) == 2, found
    for _score, mask in found:
        assert mask.shape == (334, 320) and mask.dtype == bool
        assert mask.any()
    # Masks land inside their boxes (y 228..255, x 155..271), nowhere else.
    combined = found[0][1] | found[1][1]
    ys, xs = np.nonzero(combined)
    assert ys.min() >= 228 and ys.max() < 255
    assert xs.min() >= 155 and xs.max() < 271
    assert not combined[:200, :].any()


def test_parse_masks_empty_and_threshold():
    assert sam_client.parse_masks("", 100, 100) == []
    assert sam_client.parse_masks("  \n", 100, 100) == []
    # No confidence in the payload -> kept even with a high threshold.
    assert len(sam_client.parse_masks(WIRE, 334, 320, threshold=0.95)) == 2


if __name__ == "__main__":
    test_parse_masks_placement()
    test_parse_masks_empty_and_threshold()
    print("test_sam_client: OK")
