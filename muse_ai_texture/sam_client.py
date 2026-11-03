"""Meta SAM 3.1 client on the Meta Model API (bpy-free, stdlib + parser).

SAM 3.1 is served on the same Meta Model API as Muse Image / Muse Spark:

  POST https://api.meta.ai/v1/responses
  {"model": "sam-3.1",
   "input": [{"type": "message", "role": "user", "content": [
       {"type": "input_text", "text": "<one noun phrase>"},
       {"type": "input_image", "image_url": "data:image/png;base64,..."}]}],
   "stream": true,
   "metadata": {"include_confidence": "true", "mask_encoding": "one_bit"}}

One concept per request (Meta docs: there is no multi-concept syntax), so
segmenting N concepts means N requests. The response streams
`response.output_text.delta` events whose text is the SAM wire grammar
(`<0f>id<|box;...|><|mask;...;data=H,W,ENC payload|>`); the official
`meta_sam_parser` package decodes each mask to a binary raster placed at
its box bounds. Auth is the addon's existing Meta key (META_API_KEY) —
the same key Blender already asks for. No Hugging Face token, no local
weights, no GPU.

This module must stay importable outside Blender (worker + tests).
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://api.meta.ai/v1"
DEFAULT_SAM_MODEL = "sam-3.1"


class SamAPIError(RuntimeError):
    """Raised for HTTP / payload errors from the SAM 3.1 API."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _extract_output_text(data: dict) -> str:
    """Pull the output_text lane out of a non-streamed Responses payload."""
    parts: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = content.get("text")
                if text:
                    parts.append(text)
    return "".join(parts)


def _request_output_text(png_bytes: bytes, prompt: str, api_key: str,
                         base_url: str, model: str, timeout: int) -> str:
    """One SAM 3.1 Responses call. Returns the raw segmentation text."""
    data_url = "data:image/png;base64," + base64.b64encode(png_bytes).decode()
    payload = {
        "model": model or DEFAULT_SAM_MODEL,
        "input": [{
            "type": "message", "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": data_url},
            ],
        }],
        "stream": True,
        "metadata": {"include_confidence": "true", "mask_encoding": "one_bit"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "x-api-version": "1.0.0",
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/responses",
        data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:600]
        raise SamAPIError(f"SAM 3.1 API HTTP {exc.code}: {detail}",
                          status=exc.code) from exc
    except urllib.error.URLError as exc:
        raise SamAPIError(f"Could not reach Meta API: {exc.reason}") from exc

    with response:
        content_type = response.headers.get_content_type()
        if content_type == "application/json":
            raw = response.read().decode("utf-8", errors="replace")
            try:
                return _extract_output_text(json.loads(raw))
            except json.JSONDecodeError as exc:
                raise SamAPIError(f"SAM 3.1 API returned non-JSON: {raw[:300]}") from exc
        deltas: list[str] = []
        done_text = ""
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            chunk = line[len("data:"):].strip()
            if not chunk or chunk == "[DONE]":
                continue
            try:
                event = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            kind = event.get("type", "")
            if kind == "response.output_text.delta":
                delta = event.get("delta")
                if delta:
                    deltas.append(delta)
            elif kind == "response.output_text.done":
                done_text = event.get("text") or done_text
            elif kind == "response.completed":
                inner = (event.get("response") or {})
                done_text = done_text or _extract_output_text(inner)
            elif kind in ("response.failed", "response.incomplete", "error"):
                detail = json.dumps(event)[:400]
                raise SamAPIError(f"SAM 3.1 request failed: {detail}")
    return done_text or "".join(deltas)


def parse_masks(output_text: str, height: int, width: int,
                threshold: float = 0.0):
    """Decode SAM wire text into [(score, bool mask HxW)] for one view.

    Masks below `threshold` confidence are dropped (the API is asked for
    confidence; a mask without one is kept). Higher scores sort last so
    callers painting overlaps let the best mask win.
    """
    import numpy as np
    from meta_sam_parser import (
        CompletedOutcome, decode_mask_to_raster, image_segmentation_format,
    )

    if not output_text or not output_text.strip():
        return []
    parser = image_segmentation_format().create_parser()
    parser.push(output_text)
    result = parser.finish(CompletedOutcome()).result
    found = []
    for record in result.records:
        if getattr(record, "kind", "") != "mask":
            continue
        score = record.confidence
        if score is not None and float(score) < float(threshold):
            continue
        raw = decode_mask_to_raster(record.mask)
        raster = (np.frombuffer(raw, dtype=np.uint8) if isinstance(raw, (bytes, bytearray))
                  else np.asarray(raw, dtype=np.uint8))
        mh, mw = int(record.mask.height), int(record.mask.width)
        if raster.size != mh * mw:
            continue
        bounds = record.bounds
        left, top = int(bounds.left), int(bounds.top)
        right, bottom = int(bounds.right), int(bounds.bottom)
        mask = np.zeros((height, width), dtype=bool)
        x0, y0 = max(left, 0), max(top, 0)
        x1, y1 = min(right, width), min(bottom, height)
        if x1 <= x0 or y1 <= y0:
            continue
        patch = raster.reshape(mh, mw).astype(bool)
        mask[y0:y1, x0:x1] = patch[y0 - top:y1 - top, x0 - left:x1 - left]
        if mask.any():
            found.append((1.0 if score is None else float(score), mask))
    return found


def segment_image_png(png_bytes: bytes, prompt: str, api_key: str,
                      height: int, width: int, threshold: float = 0.5,
                      base_url: str = DEFAULT_BASE_URL,
                      model: str = DEFAULT_SAM_MODEL, timeout: int = 180):
    """Segment one concept in one PNG. Returns [(score, bool mask HxW)]."""
    if not api_key:
        raise SamAPIError("No Meta API key. SAM 3.1 uses the same "
                          "META_API_KEY as Muse Image (Addon Preferences or .env).")
    if not prompt or not prompt.strip():
        raise SamAPIError("Empty concept prompt for SAM 3.1.")
    text = _request_output_text(png_bytes, prompt.strip(), api_key,
                                base_url, model, timeout)
    return parse_masks(text, height, width, threshold)
