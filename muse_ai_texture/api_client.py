"""Meta Muse Image API client (pure stdlib, no bpy imports).

Talks to the Meta Model API (OpenAI-compatible):
  Base URL : https://api.meta.ai/v1
  Model    : muse-image-1.0
  Generate : POST /images/generations  {"model", "prompt", "size", "n"}
  Edit     : POST /images/edits        {"model", "prompt", "images":[{"image_url": ...}]}
  Models   : GET  /models              (connection test)

The API key is resolved (in order) from:
  1. an explicit value (Addon Preferences override),
  2. environment variables META_API_KEY / MODEL_API_KEY / MUSE_API_KEY,
  3. a `.env` file (addon folder, .blend folder, cwd, or a custom path).

This module must stay importable outside Blender so it can be unit-tested
with the system Python.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-image-1.0"
ENV_VAR_NAMES = ("META_API_KEY", "MODEL_API_KEY", "MUSE_API_KEY")
SUPPORTED_SIZES = ("1024x1024", "1536x1024", "1024x1536")


class MuseAPIError(RuntimeError):
    """Raised for HTTP / payload errors from the Meta Model API."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class ImageResult:
    image_bytes: bytes
    image_format: str  # png | jpg | webp | gif
    model: str = DEFAULT_MODEL
    revised_prompt: str = ""


# ---------------------------------------------------------------------------
# .env handling
# ---------------------------------------------------------------------------

def parse_dotenv(path: str) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file (quotes and comments supported)."""
    values: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].lstrip()
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key:
                    values[key] = value
    except OSError:
        pass
    return values


def dotenv_candidates(extra_paths: list[str] | None = None) -> list[str]:
    """Ordered list of .env files to probe (first hit wins)."""
    candidates: list[str] = []
    for path in extra_paths or []:
        if path:
            candidates.append(path)
    addon_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(addon_dir, ".env"))
    candidates.append(os.path.join(os.getcwd(), ".env"))
    home = os.path.expanduser("~")
    if home:
        candidates.append(os.path.join(home, ".env"))
    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for path in candidates:
        norm = os.path.normpath(path)
        if norm not in seen:
            seen.add(norm)
            unique.append(path)
    return unique


def resolve_api_key(
    explicit_key: str = "",
    extra_dotenv_paths: list[str] | None = None,
) -> tuple[str, str]:
    """Return (api_key, source_description). Never raises; key may be ''."""
    if explicit_key and explicit_key.strip():
        return explicit_key.strip(), "Addon Preferences"
    for name in ENV_VAR_NAMES:
        value = os.environ.get(name, "").strip()
        if value:
            return value, f"environment variable {name}"
    for path in dotenv_candidates(extra_dotenv_paths):
        values = parse_dotenv(path)
        for name in ENV_VAR_NAMES:
            value = values.get(name, "").strip()
            if value:
                return value, f"{name} in {path}"
    return "", "not found (set META_API_KEY in a .env file or in Addon Preferences)"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def sniff_image_format(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return "png"


def _request_json(
    url: str,
    api_key: str,
    payload: dict | None = None,
    method: str = "POST",
    timeout: int = 300,
) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "x-api-version": "1.0.0",
    }
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:600]
        raise MuseAPIError(f"Meta API HTTP {exc.code}: {detail}", status=exc.code) from exc
    except urllib.error.URLError as exc:
        raise MuseAPIError(f"Could not reach Meta API ({url}): {exc.reason}") from exc
    try:
        return json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        raise MuseAPIError(f"Meta API returned non-JSON output: {raw[:300]}") from exc


def _download(url: str, timeout: int = 120) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "muse-ai-texture-blender"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except Exception as exc:  # noqa: BLE001 - surfaced to the Blender UI
        raise MuseAPIError(f"Failed to download generated image: {exc}") from exc


def _extract_image(data: dict, base_url: str, api_key: str, timeout: int) -> ImageResult:
    """Handle Images-API (`data[].b64_json|url`) and Responses-API shapes."""
    items = data.get("data") or []
    if items:
        first = items[0] or {}
        b64 = first.get("b64_json")
        if b64:
            raw = base64.b64decode(b64)
            return ImageResult(raw, sniff_image_format(raw),
                               revised_prompt=first.get("revised_prompt", "") or "")
        url = first.get("url")
        if url:
            raw = _download(url, timeout=timeout)
            return ImageResult(raw, sniff_image_format(raw))
    # Responses API fallback: output[] with image_generation_call.result (base64)
    for item in data.get("output") or []:
        if isinstance(item, dict) and item.get("type") == "image_generation_call":
            result = item.get("result")
            if result:
                raw = base64.b64decode(result)
                return ImageResult(raw, sniff_image_format(raw))
    raise MuseAPIError(f"No image in Meta API response: {json.dumps(data)[:400]}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def test_connection(api_key: str, base_url: str = DEFAULT_BASE_URL,
                    timeout: int = 30) -> tuple[bool, str]:
    """Return (ok, message). Checks auth and that muse-image-1.0 exists."""
    if not api_key:
        return False, "No API key found."
    try:
        data = _request_json(f"{base_url.rstrip('/')}/models", api_key,
                             payload=None, method="GET", timeout=timeout)
    except MuseAPIError as exc:
        return False, str(exc)
    ids = [entry.get("id", "") for entry in data.get("data") or [] if isinstance(entry, dict)]
    if DEFAULT_MODEL in ids:
        return True, f"Connected. {DEFAULT_MODEL} is available ({len(ids)} models)."
    return True, f"Connected ({len(ids)} models), but {DEFAULT_MODEL} was not listed."


def generate_image(
    prompt: str,
    api_key: str,
    size: str = "1024x1024",
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    timeout: int = 300,
) -> ImageResult:
    """Text-to-image via POST /images/generations."""
    if not prompt or not prompt.strip():
        raise MuseAPIError("Prompt is empty.")
    if not api_key:
        raise MuseAPIError("No Meta API key. Add META_API_KEY to a .env file "
                           "or paste the key in Addon Preferences.")
    payload = {"model": model or DEFAULT_MODEL, "prompt": prompt.strip(),
               "size": size or "1024x1024", "n": 1}
    data = _request_json(f"{base_url.rstrip('/')}/images/generations",
                         api_key, payload=payload, timeout=timeout)
    result = _extract_image(data, base_url, api_key, timeout)
    result.model = model or DEFAULT_MODEL
    return result


def edit_image(
    prompt: str,
    reference_images: list[bytes],
    api_key: str,
    size: str = "1024x1024",
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    timeout: int = 300,
) -> ImageResult:
    """Image edit / variation via POST /images/edits (data-URI references)."""
    if not reference_images:
        raise MuseAPIError("No reference image supplied for edit.")
    if not api_key:
        raise MuseAPIError("No Meta API key. Add META_API_KEY to a .env file "
                           "or paste the key in Addon Preferences.")
    images = []
    for raw in reference_images:
        fmt = sniff_image_format(raw)
        mime = {"png": "image/png", "jpg": "image/jpeg",
                "webp": "image/webp", "gif": "image/gif"}[fmt]
        images.append({"image_url": f"data:{mime};base64," + base64.b64encode(raw).decode()})
    payload = {"model": model or DEFAULT_MODEL, "prompt": prompt.strip(),
               "images": images, "size": size or "1024x1024"}
    data = _request_json(f"{base_url.rstrip('/')}/images/edits",
                         api_key, payload=payload, timeout=timeout)
    result = _extract_image(data, base_url, api_key, timeout)
    result.model = model or DEFAULT_MODEL
    return result
