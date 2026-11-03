---
name: baking-optimization
description: Optimize a product for the web without relying on decimate alone — retopology choice (QuadriFlow/Voxel/Limited Dissolve) plus baking Normal/AO from high-poly to low-poly before GLB export. Use for "optimize", "too many faces", "decimate looks bad", "bake".
---

# Optimization + Baking (decimate is not always the answer)

Pipeline in this addon: **analyse → choose strategy → reduce → bake →
export**. Baking is what makes reduction invisible: the polygons go,
the detail stays as textures. Always bake *before* rendering the
product or creating the GLB — maps added after export never ship.

## Choose the strategy (Smart mode does this automatically)

| Mesh character | Strategy | Why |
| --- | --- | --- |
| Hard-surface / CAD, many planar faces | Limited Dissolve (5°) | near-lossless; decimate would shred flat faces |
| Hero / deforming, manifold, >60k faces | QuadriFlow Retopo | clean quad flow; decimate destroys edge flow + UVs |
| Sculpt / photogrammetry, non-manifold | Voxel Remesh → Decimate | voxel makes it manifold first |
| Organic mid-poly (8k–60k) | Decimate Collapse + Bake | fastest, silhouette survives, bake restores detail |
| Tiny (<8k) | Limited Dissolve only | don't pay retopo cost |

Decimate's real costs: triangulated shading artifacts, destroyed UV
seams, unusable for animation. If the product deforms or is a hero
close-up, retopologise; decimate only rigid background props or when
baking will carry the detail anyway.

## Bake setup (Showcase panel → Bake, or `bake_product_maps`)

- Engine forced to Cycles (CPU, 16 samples — deterministic headless),
  **Selected-to-Active** when high ≠ low, cage extrusion 0.02,
  margin 16px (hides UV seams), tangent-space normals.
- Low-poly copy must have UVs first (`ensure_uv_map`: Smart Project,
  box-project fallback). No UVs = no bake.
- Outputs: `<product>_normal` (Non-Color → Normal Map node) and
  `<product>_ao`, pre-multiplied into a `<product>_albedo` image
  (base × AO) wired as the Base Color texture. Pre-multiplying is
  deliberate: the glTF exporter does not reliably split a shader Mix
  node into base + occlusion (it shipped the AO as the base colour —
  grey product), while a baked albedo ships correctly everywhere.
- Resolution: 1024 default; 2048 for hero products; 512 for thumbnails.
- Previous engine/device are restored after baking; a failed bake is
  reported in `bake_status` and never blocks the export.

## Order of operations (never reorder)

1. `optimize_product` (duplicate `<name>_web`, clean, reduce)
2. `bake_product_maps` (high original → web copy)
3. `create_showcase_animation` (bake the chosen variant)
4. `build_website` (exports GLB with baked maps + animation, harness-validates)

Rendering a product still (`render_image` / Modal cloud render) should
also happen after step 2, on the baked copy — otherwise the render and
the website show different products.

## Verify

Faces before→after, GLB KB, and bake status are reported by every tool.
A good result: 5–10× fewer faces, GLB under ~2 MB, no visible silhouette
change at showcase distance. If the silhouette changed, the strategy
was wrong — re-run with QuadriFlow at a higher target, don't just
raise the decimate ratio.
