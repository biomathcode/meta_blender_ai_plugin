---
name: proyecto-blender-harness
description: Blender production harness for e-commerce sites — director pipeline, catalogue camera, three-point lighting, verified GLB export (synthesised from proyecto26/blender-ai-plugin, MIT)
---

# Blender Harness — director → camera → light → export

Synthesised for Muse Harness from proyecto26/blender-ai-plugin skills
`blender-director`, `camera-cinematography`, `lighting`, `lookdev`,
`export-pipeline`, `lod-pipeline` (MIT, upstream:
https://github.com/proyecto26/blender-ai-plugin — install with
`npx skills add proyecto26/blender-ai-plugin`). Applied to the website
pipeline as stage gates; a FAIL at any gate blocks the build:

1. **Inspect** — scene audit + product frame (bbox centre/radius) before
   any render. Name the product, polycount budget and site category
   (SHOWCASE / SHOPIFY / CONFIGURATOR) up front (director brief).
2. **Camera** — product lens language: 35–50mm natural for catalogue,
   85mm+ compression for hero/detail. Azimuth 0 = front (-Y), hero at
   35°/18°, detail close at short distance. Subject readable in
   silhouette, horizon level, no tangent mergers.
3. **Light** — three-point only: Key 45° above/30° side (warm 3200–5500K
   by mood), Fill opposite at 1/4–1/2, Rim behind for separation. Area
   lights for studio softness. Never a lone light; catalogue uses the
   temp Muse Key/Fill/Rim rig when the scene has none.
4. **Look** — Principled only for GLB survival: flat PBR values and image
   textures export; procedural Noise/ColorRamp chains do not — bake
   Normal+AO (harness Step 2) before export or the web copy goes flat.
5. **Export gate** — GLB, `export_apply` as the harness sets it, Yup,
   animations as actions; verify magic `glTF`, LOD tiers, catalogue
   images and 360 frames exist (site_harness.validate_site) before
   declaring the site healthy. Names map spaces→underscores in glTF —
   reference exported names, not Blender names.
6. **360 gate** — cloudimage-360 frames are 1-based `frame-{index}.jpg`,
   one folder per finish; a missing frame fails validation, never ship
   a half spin.
