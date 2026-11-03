"""Skill library: bundled Blender skills the agent can load on demand.

Skills live as Markdown in `skills/` (authored here) and `skills/github/`
(fetched from GitHub, MIT — see skills/github/SOURCES.md). Each file has
`name:` / `description:` frontmatter. The agent sees the catalogue in its
system prompt, auto-loads matches for the user's request, and can fetch any
skill explicitly with the `get_skill` tool.
"""

from __future__ import annotations

import os
import re

_SKILL_CACHE: dict[str, dict] | None = None
MAX_SKILL_CHARS = 6000

_KEYWORDS = {
    "size-reduction": ("smaller", "file size", "reduce size", "compress", "web", "mobile", "glb weight"),
    "asset-optimization": ("optimize", "optimise", "polycount", "poly count", "lod", "game-ready", "performance"),
    "baking-optimization": ("bake", "baking", "normal map", "ambient occlusion", "retopo", "quadriflow", "decimate looks", "too many faces", "optimize product"),
    "threejs-visual": ("three.js", "threejs", "website looks", "visual quality", "flat lighting", "showcase site", "web 3d", "ibl", "environment lighting"),
    "diorama-showcase": ("diorama", "miniature", "isometric", "tabletop", "toy-scale", "tiny world"),
    "fit-repair-optimizer": ("repair", "fix mismatch", "align", "fit"),
    "muse-geometry-nodes": ("geometry nodes", "geonodes", "gn ", "displacement", "displace", "scatter"),
    "blender-mcp-workflow": ("mcp", "connection", "connect"),
    "blender-modeling": ("model", "mesh", "cube", "sword", "chair", "extrude", "bevel", "modifier"),
    "blender-materials": ("material", "metal", "glass", "wood", "shiny", "matte", "pbr"),
    "texture-workflow": ("texture", "bake", "atlas", "uv"),
    "blender-uv-texturing": ("uv", "unwrap", "stretched", "decal"),
    "blender-lighting": ("light", "lighting", "cinematic", "studio", "sunset", "shadow"),
    "blender-rendering": ("render", "cycles", "eevee", "image of", "picture"),
    "blender-animation": ("animate", "animation", "keyframe", "move over time", "spin", "loop", "turntable", "showcase animation"),
    "blender-export": ("export", "gltf", "glb", "fbx", "unity", "unreal", "three.js", "3d print"),
    "proyecto-blender-harness": ("website", "shopify", "configurator", "360", "spin",
                                 "catalogue", "catalog", "product photo", "ecommerce",
                                 "e-commerce", "store", "finish", "variant"),
}


def _skills_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")


def _parse_frontmatter(text: str) -> tuple[str, str]:
    name, description = "", ""
    header = text[:2000]
    match = re.search(r"^name:\s*(.+)$", header, re.MULTILINE)
    if match:
        name = match.group(1).strip()
    match = re.search(r"^description:\s*(.+)$", header, re.MULTILINE)
    if match:
        description = match.group(1).strip()
    return name, description


def catalogue() -> dict[str, dict]:
    """{skill_id: {name, description, path, source}} for every bundled skill."""
    global _SKILL_CACHE
    if _SKILL_CACHE is not None:
        return _SKILL_CACHE
    found: dict[str, dict] = {}
    root = _skills_dir()
    for dirpath, _dirs, files in os.walk(root):
        for filename in sorted(files):
            if not filename.endswith(".md") or filename == "SOURCES.md":
                continue
            path = os.path.join(dirpath, filename)
            try:
                with open(path, encoding="utf-8", errors="ignore") as handle:
                    text = handle.read()
            except OSError:
                continue
            name, description = _parse_frontmatter(text)
            skill_id = name or os.path.splitext(filename)[0]
            source = "github" if "github" in os.path.relpath(path, root) else "muse"
            found[skill_id] = {"name": name or skill_id, "description": description,
                               "path": path, "source": source}
    _SKILL_CACHE = found
    return found


def list_skills_text() -> str:
    lines = []
    for skill_id, info in sorted(catalogue().items()):
        lines.append(f"- {skill_id} [{info['source']}]: {info['description'][:140]}")
    return "\n".join(lines) if lines else "(no skills bundled)"


def get_skill(skill_id: str) -> str:
    info = catalogue().get(skill_id)
    if info is None:
        return f"Unknown skill '{skill_id}'. Available: {', '.join(sorted(catalogue()))}"
    with open(info["path"], encoding="utf-8", errors="ignore") as handle:
        text = handle.read()
    if len(text) > MAX_SKILL_CHARS:
        text = text[:MAX_SKILL_CHARS] + "\n…[skill truncated]"
    return text


def select_skills(prompt: str, limit: int = 2) -> list[str]:
    """Keyword-match the most relevant skill ids for a user request."""
    lowered = f" {prompt.lower()} "
    scored: list[tuple[int, str]] = []
    known = catalogue()
    for skill_id, words in _KEYWORDS.items():
        if skill_id not in known:
            continue
        score = sum(1 for word in words if word in lowered)
        if score:
            scored.append((score, skill_id))
    scored.sort(reverse=True)
    return [skill_id for _score, skill_id in scored[:limit]]
