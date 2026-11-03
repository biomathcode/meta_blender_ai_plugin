---
name: size-reduction
description: Shrink .blend and export file size — texture resizing, decimation, orphan purge, packed data, compressed save, GLB pipeline. Use for "make it smaller", "reduce file size", "optimize for web/mobile".
---

# Size Reduction (Blender)

Goal: smallest file that still looks right. Measure first with `analyze_scene`, fix the biggest contributor, re-measure.

## Where size hides (check in this order)
1. **Textures** — a 4K PNG is ~5–90 MB GPU/disk. Resize images over 1024px (web/mobile) or 2048px (desktop) with `resize_textures`. Prefer JPG/WebP over PNG for colour maps; keep PNG only where alpha/sharp data matters.
2. **Geometry** — sort objects by face count (`get_scene_info`). Decimate background/high-poly meshes with `optimize_object` (ratio 0.3–0.6). Never decimate hero/close-up meshes below visual quality; check silhouette.
3. **Packed data** — unpacked-but-missing or packed-but-huge images bloat .blend. Pack only what ships; save with compression (`save_file` uses compressed save).
4. **Orphans** — unused materials/images/meshes: `purge_orphans` (runs orphan cleanup several times).
5. **Modifiers baked in** — Array/Mirror applied = multiplied geometry. Keep modifiers live; export with apply=False.

## Rules
- Never use a one-click "optimize everything" blindly: decimation is irreversible once applied/saved. Prefer Decimate modifiers (non-destructive) and report before/after face counts.
- Textures: resize a copy, keep the original file on disk untouched when possible; report old → new pixel sizes.
- GLB for web: export without Draco (`export_glb`), then externally resize → WebP → Draco last (Draco is irreversible, never re-encode Draco).
- Report the result as: faces before→after, texture MB before→after, file MB before→after.

## Agent tool mapping
`analyze_scene` → `resize_textures(max_size)` / `optimize_object(name, ratio)` / `optimize_scene(...)` → `purge_orphans` → `save_file` / `export_glb`.
