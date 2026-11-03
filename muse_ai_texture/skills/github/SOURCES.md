# Bundled GitHub skills — sources & licenses

Fetched 2026-10-31 via the Skills ecosystem (skills.sh). All MIT-licensed.
Install them in your coding agent with the commands shown; the copies here
let this Blender agent load the same guidance in-process.

| File | Upstream | Install |
|---|---|---|
| asset-optimization.md, asset-optimization-lod.md | [arjun988/blender-skills](https://github.com/arjun988/blender-skills) (MIT) | `npx skills add arjun988/blender-skills@asset-optimization` |
| texture-workflow.md | [arjun988/blender-skills](https://github.com/arjun988/blender-skills) (MIT) | `npx skills add arjun988/blender-skills@texture-workflow` |
| cc-blender-modeling.md, cc-blender-materials.md, cc-blender-lighting.md, cc-blender-rendering.md, cc-blender-animation.md, cc-blender-export.md, cc-blender-uv-texturing.md, cc-fit-repair-optimizer.md | [RobLe3/cc-blender-skill](https://github.com/RobLe3/cc-blender-skill) (MIT) | `npx skills add roble3/cc-blender-skill@blender-modeling` (etc.) |

Related projects (not bundled): [Blender MCP](https://github.com/ahujasid/blender-mcp)
(socket server this addon detects on port 9876),
[freshtechbro/claudedesignskills blender-web-pipeline](https://skills.sh/freshtechbro/claudedesignskills/blender-web-pipeline),
[vladmdgolam/agent-skills blender-mcp](https://skills.sh/vladmdgolam/agent-skills/blender-mcp).

## Researched 2026-11-02 (synthesised into authored skills, not copied)

The authored skills in `skills/` (`threejs-visual.md`,
`diorama-showcase.md`, `baking-optimization.md`) synthesise these
sources — read them upstream for the full text:

| Upstream | What was taken |
|---|---|
| [roslesmedia threejs-lighting-environment skill](https://github.com/roslesmedia/security-cams-iran-site-2/blob/HEAD/skills/threejs-lighting-environment/SKILL.md) | Studio-quality Three.js lighting: HDRI/RoomEnvironment IBL, tone-mapping choice, soft + contact shadows, baked AO |
| [sloemo01/diorama](https://github.com/sloemo01/diorama) | Pixel-art diorama playbook: locked camera, palette/dither, toy-scale cast |
| [educlopez/diorama](https://github.com/educlopez/diorama) | `diorama-worlds`: Three.js miniature worlds, miniature/pixel/halftone/blueprint finishes |
| [threejs-reference-diorama skill](https://github.com/annac777/xi4u/blob/HEAD/skills/threejs-reference-diorama/SKILL.md) | Reference-driven procedural dioramas, illustration-like lighting |
| three.js examples (`RoomEnvironment`, `webgl_loader_gltf`) + `threejs-lighting` skill | PMREM IBL, PCFSoft shadow tuning (`bias`/`normalBias`/`radius`), `environmentIntensity` (r163+) with `envMapIntensity` fallback |

## Added 2026-11-03 (website harness upgrade)

| File | Upstream | Install |
|---|---|---|
| proyecto-blender-harness.md (synthesised) | [proyecto26/blender-ai-plugin](https://github.com/proyecto26/blender-ai-plugin) skills: blender-director, camera-cinematography, lighting, lookdev, export-pipeline, lod-pipeline (MIT) | `npx skills add proyecto26/blender-ai-plugin` |
| scroll-experience (agent-side, .claude/skills) | davila7/claude-code-templates (Apache 2.0) | `npx skills add davila7/claude-code-templates@scroll-experience --agent claude-code` |
| threejs skills guidance (agent-side) | [cloudai-x/threejs-skills](https://github.com/cloudai-x/threejs-skills): loaders, lighting, interaction, asset-pipeline | `npx skills add cloudai-x/threejs-skills` |
| UI skills guidance (agent-side) | [ui-skills.com](https://www.ui-skills.com/) via `npx ui-skills`: mengto/3d-orbit-inspect-demo, mengto/design-first-ui-prompting (categories: 3d, frontend) | `npx ui-skills get mengto/3d-orbit-inspect-demo` |
| 360 viewer | [Scaleflex/cloudimage-360-view](https://github.com/Scaleflex/cloudimage-360-view) v4.10.0 CDN (MIT) | `<script src="https://cdn.cloudimage.io/360-view/4.10.0/360-view.min.js">` |
