# Muse Harness — Blender addon (Meta Muse Image 1.0)

Generate textures with **Meta Muse Image 1.0** and use them in Blender
materials and **Geometry Nodes** — the [ComfyUI-BlenderAI-node](https://github.com/AIGODLIKE/ComfyUI-BlenderAI-node)
workflow, but **Meta Muse only** (no ComfyUI, no Stable Diffusion).

Prompt → `muse-image-1.0` on the Meta Model API → texture on your mesh,
plus a Geometry Nodes group that displaces geometry from the same image.

## Install

1. Zip the `muse_ai_texture` folder, or use the provided `muse_ai_texture.zip`.
2. Blender → **Edit → Preferences → Add-ons → Install…** → pick the zip → enable
   **Muse Harness**.
3. Add your API key (next section). Requires Blender 4.2+ (tested on 5.4).

## API key (.env)

Get a key at [dev.meta.ai](https://dev.meta.ai) → API Keys (keys look like `LLM|…|…`).
The addon reads `META_API_KEY` (aliases: `MODEL_API_KEY`, `MUSE_API_KEY`) from,
in order:

1. Addon Preferences → *Meta API Key (override)*
2. Environment variables
3. A `.env` file — in the **addon folder**, next to the **.blend file**, in the
   working directory, or at the path set in Preferences → *.env File*

```ini
# .env
META_API_KEY=LLM|your-key-here
```

Never commit a real `.env`. Only [`.env.example`](muse_ai_texture/.env.example)
(no key) ships in the zip.

## Cloud Render — camera viewport on Modal

Render the **scene camera (viewport)** in the cloud, following Modal's
[Blender video example](https://modal.com/docs/examples/blender_video):
a container image with Blender as the `bpy==4.5.0` package renders frames
on Modal, animations fan out with `render.starmap` across containers, and
an ffmpeg function stitches them into an MP4.

![Addon snapshot — Cloud Render panel and Modal token fields](docs/addon_cloud_render_snapshot.png)

*Snapshot: panel mockup drawn from the shipped UI code, with a real
320×240 cloud render (CPU container) in the viewport.*

Setup:

1. Install the Modal CLI: `pip install modal`.
2. Add your tokens — get them at
   [modal.com/settings/tokens](https://modal.com/settings/tokens) or run
   `modal token new`. Either paste **Modal Token ID / Secret** in
   Edit → Preferences → Add-ons → Muse Harness, or put them in the
   same `.env` as your Meta key:

   ```ini
   MODAL_TOKEN_ID=ak-...
   MODAL_TOKEN_SECRET=as-...
   ```

   Resolution order matches the Meta key: Preferences → environment →
   `.env`. Tokens are passed to the CLI via its environment only — never
   written into the generated Modal app or the command line.
3. Click **Test Modal** in Preferences (or the Cloud Render panel) — it
   checks the tokens, the CLI, and reports where the tokens came from.

Use — in **View3D → Sidebar (N) → Muse AI → Cloud Render — Modal**:

1. Set an active camera and your render settings (resolution, engine,
   samples, frame range) — the cloud render uses them **as saved in the
   scene**; only the Cycles device is switched (GPU CUDA with CPU fallback,
   or CPU when *Use GPU* is off).
2. Pick **Output: Image** (single frame) or **Animation / Video**
   (`frame_start–frame_end`, every *Frame Step*, in parallel up to
   *Max Containers*, stitched to `cloud_render.mp4` on Modal), then press
   the one **Render … on Modal** button. If the tokens are missing, the
   panel shows the exact `MODAL_TOKEN_ID=` / `MODAL_TOKEN_SECRET=` lines
   to add to your `.env`.
3. The scene — including unsaved changes — is uploaded via a temporary
   copy (`_muse_cloud_scene.blend`); your own file is never overwritten.
   Results land in `muse_cloud_renders/` next to the .blend (the generated
   `muse_modal_render.py` app is kept there too, for inspection/re-runs
   with `modal run`). A still is loaded back into Blender as an image.

GPU note: GPU types (L40S default, also L4/A10G/T4/A100/H100) need a
payment method on the Modal account; without one Modal returns
“Please add a payment method to use … GPU functions” and the panel shows
it — untick *Use GPU* to render on CPUs instead. Link external assets or
pack them (`File → External Data → Pack Resources`) before rendering, as
only the .blend file is uploaded.

## Gaussian Splat — SAM 3.1 segmentation into separate objects

Split one `.spz` Gaussian splat into separate Blender objects by naming
the objects. **View3D → Sidebar (N) → Muse AI → Gaussian Splat —
SAM 3.1 Segmentation**:

1. **Import SPZ** (or select an existing PointCloud splat). Blender 5.3+
   imports `.spz` natively as a splat point cloud.
2. Type **Objects to Segment** (comma-separated noun phrases, e.g.
   `sand, rock, shell, vegetation`). Only these objects are segmented —
   there is no automatic / segment-everything mode.
3. **Segment & Separate**. The addon exports the points, renders 16
   orbit views with its own fast point rasteriser, segments each typed
   object on every view with Meta **SAM 3.1** (`sam-3.1` on the Meta
   Model API, `POST /v1/responses` — one request per object per view),
   votes the 2D masks back onto the Gaussians (majority vote with a
   depth/occlusion test), splits same-object clusters into individual
   instances, and creates one native splat object per instance
   (`<splat>_<object>_01`, …) using Blender 5.4's point delete path
   (Geometry Nodes `Delete Geometry` on a `segment_id` attribute —
   `radiance:base`, `scale`, `rotation` untouched). Nothing is deleted:
   unlabelled Gaussians become `<splat>_background` and the source
   object is kept, hidden. **Separate Again** re-splits from the stored
   labels without calling SAM again.

SAM 3.1 runs on the Meta Model API with the **same Meta key** as Muse
Image (`META_API_KEY` in a `.env` file or Addon Preferences) — no
Hugging Face token, no gated weights, no local GPU. A light external
worker (project-local `.venv-splat` from **Create Worker Env**; only
numpy + pillow + `meta-sam-parser`) renders the views and does the
voting; only the rendered view images go to the API. Each run leaves a
job folder (`muse_splat/<timestamp>_<splat>/` next to the .blend) with
rendered views, SAM label images, the worker log and `report.json`.

Core math (`splat_core.py`, pure NumPy) is covered by
`tests/test_splat_core.py`, and SAM mask decoding by
`tests/test_sam_client.py` (`.venv-splat/bin/python tests/test_splat_core.py`).

## Product Showcase — LODs → animate → CMS → Three.js website

Turn the selected model into a scroll-driven web product showcase without
leaving Blender. **View3D → Sidebar (N) → Muse AI → Product Showcase (Web)**
runs the four steps (the Muse agent can run the same steps — ask it with
the *Product showcase site* quick prompt):

1. **Create LODs (Low / Medium / High)** — instead of crushing one web
   copy, three versions are kept as `<name>_lod_high` / `_lod_medium` /
   `_lod_low` (original kept): High is cleanup-only at ratio 1.0 (full
   detail), Medium and Low decimate to the panel ratios (defaults
   0.45 / 0.12). *Build Website* exports `product_high.glb`,
   `product_medium.glb` and `product_low.glb` (+ `product.glb` mirroring
   the default tier), and the site header offers a **Quality Low /
   Medium / High** switcher — the visitor's choice is remembered, the
   Blender *Site Default Quality* (Auto / Low / Medium / High) picks the
   first load, and Auto starts Low on mobile / data-saver, High on
   desktop. Switching swaps the GLB in place (animation position kept)
   and caps the pixel ratio per tier.
2. **Bake Detail onto Medium / Low LODs** — bakes Normal + AO from the
   original high-poly mesh onto the Medium and Low LODs (Cycles
   Selected-to-Active; High needs no bake)
   and wires them into its material (AO pre-multiplied into a baked
   albedo so the glTF exporter ships it correctly). Run this **before
   rendering the product or building the GLB** — it is what makes the
   polygon reduction invisible. *Build Website* re-bakes automatically
   when *Bake Detail Before Export* is on.
3. **Create Showcase Animation** — bakes one of ten variants into the
   LODs (shared action; *Turntable*, *Turntable + Float*, *Hero Reveal*,
   *Orbit Reveal*, *Float Spin*, *Pulse*, *Swing*, *Tilt Orbit*,
   *Diorama Orbit*, *Explode Float*). It is exported inside the GLB and
   scrubbed by GSAP ScrollTrigger on the site; at the top of the page
   it plays on its own.
4. **CMS (stored in this .blend)** — all site copy lives in the addon:
   *Languages* (seeded `en` default + `hi`; add `es`, `fr`, … with the code +
   label fields) and *Entries* (`hero_title`, `story_body`, `feature_1_*`, …,
   each with one text per language). This is the site's
   internationalization layer: a blank translation falls back to the
   default language on the site — never to an empty string. Edit the
   selected entry's per-language texts right in the panel, then rebuild.
5. **Build Website** — bakes (if enabled), exports the three LOD GLBs and
   writes a static site (Three.js pinned + GSAP ScrollTrigger, CDN):
   hero / story / features / specs / CTA sections over a fixed 3D stage,
   drag-to-orbit, scroll-scrubbed Blender animation + scroll dolly, and
   a language switcher (choice is remembered). Lighting is IBL-first
   (PMREM RoomEnvironment) with a 3-point rig and PCFSoft shadows;
   pick a preset (*Studio*, *Studio Soft*, *Sunset*, *Dramatic*,
   *Diorama*) plus Environment Intensity / Exposure in the panel.
   *Diorama Mode* locks the camera to a 35.264° isometric miniature
   view on a plinth. The CMS is baked into `index.html` and also
   exported as `content.json` + `locales/<code>.json` next to it.
   A build **harness** then validates the export (GLB magic, embedded
   CMS, no leftover placeholders), writes `manifest.json`, picks a
   free port, and generates a one-command `serve.py`. The panel's
   harness box shows **● Site is LIVE** with the quick link
   (e.g. http://127.0.0.1:8000/) or **○ not running** with the exact
   start command — *Check If Site Is Running* re-probes on demand.

![Generated showcase site (Blender test model, optimized 31,488 → 15,500 faces)](docs/showcase_website_snapshot.png)

Run the generated site (browsers block GLB loads from `file://`):

```bash
cd muse_website          # next to your .blend, or the folder set in the panel
python3 serve.py 8000    # generated by the harness (or: python3 -m http.server 8000)
```

Then open http://127.0.0.1:8000/ in a browser — the Showcase panel's
harness box shows this exact link and whether the site is live on that
port. After any CMS edit in Blender, press **Build Website** again —
the site is regenerated from the .blend.

Agent tools for the same workflow: `optimize_for_web` (creates the LODs),
`bake_product_maps`, `create_showcase_animation` (ten variants),
`seed_cms`, `set_cms_text` (e.g. `hero_title` / `hi`), `build_website`,
and `check_site` (harness probe + validation).

## Use — textures

The sidebar is four boxes — **Status** (Muse Image + Modal readiness),
**Create** (one Muse Image flow with *Texture / Edit Last / Geometry Nodes*
variants), **Library & Apply** (history + apply + GN modifier), and
**Cloud Render — Modal** (*Image / Animation* output variants). The
**Muse Agent Chat** panel sits above it and the Product Showcase panel
starts collapsed.

Open **View3D → Sidebar (N) → Muse AI** (also in the Shader and Geometry
Nodes editors):

1. Select a mesh. Type a prompt, e.g. `weathered red brick wall with subtle moss`.
2. Pick a size (1024×1024 / 1536×1024 / 1024×1536) and style. *PBR Texture* +
   *Seamless* appends tileable-texture guidance to the prompt.
3. **Generate Texture** — generation runs on a background thread. The result is
   saved to `muse_textures/` next to the .blend (packed into the file), loaded
   as an image, added to **History**, and applied as a PBR material
   (Base Color + derived Bump and Roughness; Smart UV Project if the mesh has
   no UVs).
4. **Edit Last Image** re-prompts the last result via `POST /v1/images/edits`
   (e.g. `make it older, add cracks`).

## Agent Chat — Muse Spark + Blender MCP tools

The **Muse Agent Chat** panel (View3D → Sidebar → Muse AI, above the texture
panel) is a full Blender agent powered by **Meta Muse Spark**
(Chat Completions tool-calling on `https://api.meta.ai/v1`). The panel
shows **only the last response** (the full transcript is kept in the
.blend for the agent's context). The model's Markdown is rendered as
structure — headings, bullets, numbered lists, code fences, quotes and
tables are drawn readably in the sidebar instead of dumping raw `**`,
`##` and ``` markers (Blender labels have no rich text, so
`_draw_markdown` in `panels.py` flattens inline markers and indents by
block type); the agent is prompted to answer in short Markdown for this
renderer. A **Task** switch routes models:
*Blender Task* → lower model (`muse-spark-1.1`) for build / texture /
optimize / render work, *Website / Showcase* → higher model
(`muse-spark-1.3`) for site builds, *Custom* → the model picked in the
panel. Quick actions cover scene info, build+light, texture selection,
optimize, studio render, **Cloud render…** (the agent asks *image or
animation?*, then asks for `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` in
your `.env` if Modal is not set up) and showcase-site builds:

> "Create a brick cube, light it like a studio shot, then optimize the scene."

The agent loops — Spark plans → calls a Blender tool → sees the result →
repeats (up to *Max Steps*) — until it answers. LLM calls run on a worker
thread; tools always execute on Blender's main thread. *Stop* halts after the
current step; every tool call and result is shown in the transcript.

**Blender MCP connection.** The agent runs inside Blender on the same `bpy`
API the [Blender MCP](https://github.com/ahujasid/blender-mcp) server exposes,
so in-process execution is used (socket round-trips from the main thread
would deadlock the MCP server's own executor). If the Blender MCP addon is
serving on `127.0.0.1:9876`, **Check MCP** reports it as detected and external
MCP clients can drive the same Blender; outside Blender, the bridge routes
`execute_code` over that socket. See the bundled `blender-mcp-workflow` skill.

**Tools (37):** scene inspection (`get_scene_info`, `list_objects`,
`get_object_info`), modelling (`create_primitive`, `transform_object`,
`delete_object`, `duplicate_object`, `add_modifier`, `apply_modifier`),
materials/textures (`create_material`, `generate_texture` via Muse Image,
`add_gn_texture`), optimization (`analyze_scene`, `optimize_object`,
`clean_mesh`, `resize_textures`, `purge_orphans`, `optimize_scene`),
light/camera/render (`add_light`, `add_camera`, `set_render_settings`,
`render_image`), files (`save_file`, `export_glb`), animation
(`keyframe_object`, `set_frame_range`), skills (`list_skills`, `get_skill`),
MCP (`mcp_health`), and `execute_blender_python` — arbitrary `bpy` for
anything else, so the agent can perform any Blender action. Gate it with
*Allow Python Execution* in the panel (on by default; turn it off to restrict
the agent to structured tools only).

**Skills.** The agent auto-loads relevant skills per request and can fetch
any of them with `get_skill`. Bundled in [skills/](muse_ai_texture/skills):
authored `size-reduction`, `muse-geometry-nodes`, `blender-mcp-workflow`,
`baking-optimization` (retopo choice + bake-before-export),
`threejs-visual` (IBL-first Three.js lighting/quality, researched from
the three.js examples and lighting-environment skills) and
`diorama-showcase` (locked isometric miniature presentation, researched
from the open diorama skills — see SOURCES.md),
plus GitHub skills under [skills/github/](muse_ai_texture/skills/github/SOURCES.md)
(MIT, fetched from GitHub): `asset-optimization` + `texture-workflow`
([arjun988/blender-skills](https://github.com/arjun988/blender-skills)) and
modeling/materials/lighting/rendering/animation/export/UV/fit-repair
([RobLe3/cc-blender-skill](https://github.com/RobLe3/cc-blender-skill)).
Install the same skills in your coding agent:

```bash
npx skills add arjun988/blender-skills@asset-optimization
npx skills add arjun988/blender-skills@texture-workflow
npx skills add roble3/cc-blender-skill@blender-modeling
```

## Use — Geometry Nodes

Geometry Nodes cannot call HTTP, so the addon bridges it (same constraint the
ComfyUI plugin works around with its server):

- **Add Muse GN Modifier** builds a reusable **`Muse GN Texture`** node group
  and puts it on the active mesh. Group inputs: `Geometry`, `Image`,
  `Strength`, `Texture Scale`, `Material`. Inside, it samples the generated
  image by position, stores a `muse_height` point attribute, displaces along
  normals, and sets the material — subdivide the mesh for visible displacement.
- **Generate for Geometry Nodes** (GN editor panel, or *Generate + Geometry
  Nodes* in the 3D View) uses the per-object **GN Prompt** on the active mesh,
  generates, and feeds the image into the modifier and the material.
- In the Geometry Nodes editor, **Add → Muse GN Texture** inserts the group
  node into any tree by hand; wire any image into its `Image` socket.

## API reference (Meta Model API)

| | |
|---|---|
| Base URL | `https://api.meta.ai/v1` |
| Model | `muse-image-1.0` |
| Generate | `POST /images/generations` `{model, prompt, size, n}` → `data[].b64_json` |
| Edit | `POST /images/edits` `{model, prompt, images[].image_url, size}` |
| Auth | `Authorization: Bearer <META_API_KEY>`, `x-api-version: 1.0.0` |
| Price | ~$0.01 / image (Meta list price) |

## Files

| File | Role |
|---|---|
| [__init__.py](muse_ai_texture/__init__.py) | Addon entry point / registration |
| [api_client.py](muse_ai_texture/api_client.py) | Meta API client + .env loading (bpy-free, testable) |
| [operators.py](muse_ai_texture/operators.py) | Async generate/edit, apply, GN operators |
| [nodes.py](muse_ai_texture/nodes.py) | PBR material builder + `Muse GN Texture` group |
| [panels.py](muse_ai_texture/panels.py) | 3D View / Shader / Geometry Nodes UI |
| [properties.py](muse_ai_texture/properties.py) | Scene/Object settings + history |
| [preferences.py](muse_ai_texture/preferences.py) | Key override, endpoints, folders |
| [spark_client.py](muse_ai_texture/spark_client.py) | Muse Spark chat + tool-calling client |
| [agent_loop.py](muse_ai_texture/agent_loop.py) | Agentic loop (Spark ↔ tools) |
| [agent_tools.py](muse_ai_texture/agent_tools.py) | 37 Blender tools for the agent |
| [mcp_bridge.py](muse_ai_texture/mcp_bridge.py) | Blender MCP socket bridge (port 9876) |
| [chat_operators.py](muse_ai_texture/chat_operators.py) | Async chat send/stop/clear, MCP check |
| [modal_client.py](muse_ai_texture/modal_client.py) | Modal credentials, generated Modal app (`bpy` image, parallel frames, ffmpeg), CLI runner (bpy-free, testable) |
| [showcase.py](muse_ai_texture/showcase.py) + [showcase_operators.py](muse_ai_texture/showcase_operators.py) | Product Showcase core + operators: Low/Medium/High LOD creation, bake onto Medium/Low, ten animation variants, CMS seeding, multi-GLB + site export with quality switcher |
| [site_harness.py](muse_ai_texture/site_harness.py) | Build harness (bpy-free): site validation, free-port pick, live-server probe, manifest + `serve.py` generation |
| [web_cms.py](muse_ai_texture/web_cms.py) | In-Blender CMS / i18n logic: seed copy (en+hi), locale building with default-language fallback (bpy-free, testable) |
| [site_template.py](muse_ai_texture/site_template.py) | Generated Three.js + GSAP ScrollTrigger showcase template (embedded CMS, language switcher) |
| [cloud_operators.py](muse_ai_texture/cloud_operators.py) | Async cloud render (camera still/animation), Modal test, output folder |
| [splat_core.py](muse_ai_texture/splat_core.py) | Splat segmentation core (NumPy only, testable): orbit cameras, point rasteriser, depth-tested multi-view voting, voxel instance splitting |
| [sam_client.py](muse_ai_texture/sam_client.py) | SAM 3.1 client (bpy-free): one Meta Model API `/v1/responses` request per typed object, streamed wire-text parsing via `meta_sam_parser` into full-frame masks |
| [splat_worker.py](muse_ai_texture/splat_worker.py) | External splat worker (never imported by Blender): renders views, calls SAM 3.1 via `sam_client` with the addon's Meta key, votes, writes labels |
| [splat_operators.py](muse_ai_texture/splat_operators.py) | Splat operators: SPZ import, point export, worker launch with live progress, GN Delete-Geometry separation into native splat objects, worker-env setup/check |
| [skills.py](muse_ai_texture/skills.py) + [skills/](muse_ai_texture/skills) | Skill catalogue (authored + GitHub, MIT) |

## Troubleshooting

- **No API key** — check the key source line in the Muse AI panel; Preferences
  shows where the key was found. `Test` verifies it against `GET /models`.
- **HTTP 401/403** — key is not a Model API key from dev.meta.ai.
- **Flat displacement** — the GN group displaces vertices; add a Subdivision
  Surface modifier (or subdivide) before the Muse modifier.
