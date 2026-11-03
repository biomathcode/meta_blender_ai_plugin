---
name: threejs-visual
description: Make Three.js product showcases look premium — IBL-first lighting, ACES tone mapping, soft shadows, material/env tuning, camera and scroll choreography. Use for "make the website 3D look better", "visual quality", "lighting looks flat", Three.js site polish.
---

# Three.js Visual Quality (product showcase)

Source synthesis: three.js examples (`RoomEnvironment`, `webgl_loader_gltf`),
`threejs-lighting-environment` skill (roslesmedia, MIT-style example notes),
drei `Environment` guidance, and the `web3d` method (forms → materials →
light → effects). Baked into `site_template.py`; retune via the Showcase
panel Lighting Preset / Environment Intensity / Exposure, then rebuild.

## The non-negotiables (in order)

1. **IBL first, lights second.** Never ship a lone `DirectionalLight`.
   `PMREMGenerator` + `RoomEnvironment` (or a 1k–2k `.hdr`):
   ```js
   const pmrem = new THREE.PMREMGenerator(renderer);
   scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
   if ('environmentIntensity' in scene) scene.environmentIntensity = 0.9; // r163+
   // Fallback (older three): after GLB load, set material.envMapIntensity = 0.9.
   ```
   IBL gives PBR reflections + diffuse fill for free; metals/glass look
   grey without it.
2. **Colour pipeline.** `renderer.toneMapping = THREE.ACESFilmicToneMapping`,
   `toneMappingExposure` 1.0–1.15, `outputColorSpace = THREE.SRGBColorSpace`.
   Baked normal/AO maps must be `Non-Color`; base colour is sRGB.
3. **One shadow light.** Only the key casts shadows (perf). 
   `renderer.shadowMap.type = THREE.PCFSoftShadowMap`, key
   `shadow.mapSize` 2048, tight frustum around the product (±4 for a
   2.3-unit normalised model), `bias -0.0001`, `normalBias 0.02`,
   `radius` 2 (crisp/DRAMATIC) → 8 (soft/STUDIO_SOFT).
4. **Ground the product.** `ShadowMaterial` catcher (opacity 0.28) over a
   matte disc, or a diorama plinth. Floating products always look cheap.
5. **Normalise then frame.** Centre + scale the GLB to ~2.3 units
   (`Box3`), camera 42° (36° diorama), scroll dolly via FOV 42→35 —
   never move the camera in a way that fights `OrbitControls`.

## Lighting presets (Blender panel → site config)

| Preset | Key:Fill:Rim | Character |
| --- | --- | --- |
| STUDIO | warm 2.6 / cool 0.7 / 1.5 | default product hero |
| STUDIO_SOFT | 1.7 / 1.0 / 0.8, radius 8 | matte, cosmetics, fabric |
| SUNSET | warm-orange key, teal fill | lifestyle, outdoor |
| DRAMATIC | 3.4 / 0.18 / 1.9, radius 2, env ×0.55 | jewellery, premium noir |
| DIORAMA | see `diorama-showcase` | locked isometric miniature |

Colour temps: tungsten key `(1.0,0.95,0.85)`, daylight fill
`(0.85,0.9,1.0)`, rim `(0.7,0.85,1.0)` — warm key + cool fill is the
Hollywood teal/orange read.

## Materials checklist (from the GLB)

- Metal: roughness 0.25, metalness 1; paint/plastic 0.4/0; wood/stone
  0.8/0; rubber/cloth 0.9/0; glass needs `MeshPhysicalMaterial`
  transmission in Blender so glTF exports it.
- If a material looks flat, check in order: env intensity → roughness
  map present? → baked AO multiplying base colour? → normal map wired?
- Cap `setPixelRatio(min(devicePixelRatio, 2))`; antialias on.

## Choreography

- GSAP ScrollTrigger scrubs the Blender-baked clip (`action.time =
  progress * duration`, `mixer.update(0)`); at the top (`p < 0.005`)
  the clip plays on its own. Honour `prefers-reduced-motion`: no scrub,
  no idle spin.
- Idle auto-rotate only at the top and only when the preset allows it;
  diorama mode sways ±0.06 rad instead of spinning.

## Pitfalls

| Symptom | Fix |
| --- | --- |
| Flat / grey product | IBL missing or envIntensity 0 |
| Shadow acne / stripes | `normalBias 0.02`, check tight frustum |
| Blown highlights | exposure ↓, env ↓, key ≤ 3.4 |
| Washed-out diorama | disable fog/haze (kills miniature illusion) |

## Agent tool mapping

Blender: set Showcase Lighting Preset / Env Intensity / Exposure →
`create_showcase_animation` → `build_website`. Verify in the generated
`manifest.json` (`config.lightingPreset`) and open the live URL.
