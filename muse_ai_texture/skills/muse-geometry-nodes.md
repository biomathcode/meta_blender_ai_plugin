---
name: muse-geometry-nodes
description: Use the Muse GN Texture group and Geometry Nodes in this addon — texture-driven displacement, muse_height attribute, scattering basics. Use for Geometry Nodes, displacement, procedural geometry.
---

# Muse Geometry Nodes

## The Muse GN Texture group
- Built by `add_gn_texture(object)` / the "Add Muse GN Modifier" button. Group inputs: Geometry, Image, Strength (default 0.08), Texture Scale, Material.
- It samples the Image by object Position, stores a `muse_height` point attribute (reuse it in Shader Editor via Attribute node), displaces along normals by `(height-0.5) * Strength`, and sets the Material.
- **Displacement needs vertices**: add a Subdivision Surface modifier (level 2–3) or subdivide the mesh *before* the Muse modifier, or nothing visibly moves. Order: Subsurf → Muse GN.
- Texture Scale tiles the sample: >1 = finer detail, <1 = broader features. Strength is in metres; start 0.03–0.15.
- Generate the driving image first with `generate_texture` (tileable prompts work best: "seamless tileable … top-down").

## Geometry Nodes good practice
- Prefer named attributes (`muse_height`) over anonymous ones when a shader needs the data.
- Keep the group reusable: expose Strength/Scale/Material as group inputs instead of hard-coding values inside.
- Check the evaluated result (`get_object_info` face counts) after adding subdivision — face count explodes fast (level 3 on a cube ≈ 4k faces).
- For scattering/placement requests that the Muse group doesn't cover, use `execute_blender_python` to build a dedicated node group (Instance on Points + Point Distribute equivalents), then verify counts.

## Agent tool mapping
`generate_texture` → `add_gn_texture(object, strength, scale)` → `add_modifier(object, SUBSURF)` if displacement is invisible → `get_object_info` to verify.
