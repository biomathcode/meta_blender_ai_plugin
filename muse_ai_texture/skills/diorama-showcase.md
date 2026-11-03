---
name: diorama-showcase
description: Present a product as a miniature diorama — locked isometric camera, plinth, toy-scale lighting, no fog/haze. Use for "diorama", "miniature world", "isometric showcase", "tabletop model look".
---

# Diorama Showcase (miniature product presentation)

Synthesis of the open diorama skills: `sloemo01/diorama` (pixel-art
diorama playbook: locked camera, palette snap, ordered dither, inked
contour, toy-scale cast), `educlopez/diorama` (`diorama-worlds`:
Three.js miniature worlds, four finishes — miniature / pixel /
halftone / blueprint), and `threejs-reference-diorama` (reference-driven
procedural dioramas, illustration-like lighting, optional pixel
post-processing). This addon implements the *product* subset: one hero
product on a plinth, not a full populated world.

## Rules that make it read as a diorama

1. **Locked isometric camera.** Elevation exactly 35.264°
   (`atan(1/√2)`), azimuth constrained to ±0.9 rad, polar locked to
   ±0.12 rad around isometric. No zoom, no pan, no flip. In Blender
   this is the `DIORAMA_ORBIT` animation (X tilt baked at 35.264°);
   on the site it is `CFG.dioramaMode` + the `DIORAMA` lighting preset.
2. **A base that says "model".** Cylinder plinth (radius 1.55–1.7,
   height 0.22) under the product, contact shadow on top of it. A
   floating product on an infinite floor is a viewer, not a diorama.
3. **Toy-scale lighting.** Slightly higher hemisphere fill (0.5),
   warm key with soft shadows (radius 6), gentle rim. Keep materials
   matte-bright; tilt-shift blur is a post effect — the miniature
   illusion breaks with fog/haze, so fog stays OFF.
4. **Restricted motion.** No full turntable spin. The baked
   `DIORAMA_ORBIT` sway (±0.06 rad idle) or a slow constrained orbit
   only. Reduced-motion visitors get a static miniature.
5. **Scale cues (when the scene has room).** Tiny props at product
   scale (crates, cones, a 1.7-unit figure silhouette) sell miniature
   better than any shader. Keep them low-poly and matte.

## Finishes (from diorama-worlds, applied as site tuning)

| Finish | Site tuning |
| --- | --- |
| Miniature (default) | DIORAMA preset as above, ACES 1.08 |
| Pixel | render at 0.5× pixel ratio + `image-rendering: pixelated` (opt-in CSS) |
| Halftone / blueprint | single-hue env + desaturated materials — art-direct in Blender, not in JS |

## Blender → site mapping

- Panel: Lighting Preset = `Diorama (miniature)`, tick **Diorama Mode**,
  Animation = `Diorama Orbit`. Rebuild — the site locks the camera,
  adds the plinth, and labels the badge `DIORAMA · diorama`.
- Do NOT combine Diorama Mode with `SUNSET`/`DRAMATIC` presets or with
  a free `Turntable 360°`: the locked camera + full spin fights itself.

## Pitfalls

| Symptom | Fix |
| --- | --- |
| Looks like a normal viewer | camera not locked / no plinth |
| Miniature looks huge | add scale-cue props; raise camera FOV narrowing (36°) |
| Washed out | fog or haze enabled — remove it |
| Product clips the plinth | normalise to 2.3 units, lift +0.22 in diorama mode |
