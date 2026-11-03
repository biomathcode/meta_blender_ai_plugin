# UI consolidation — Muse AI Texture panels

## Design language
- Audited surface: Blender sidebar panels in `muse_ai_texture/panels.py` (View3D texture panel, Product Showcase panel, Agent Chat panel) on Blender 5.4.
- Design sources: current `panels.py` boxes and operator ids in `operators.py`, `cloud_operators.py`, `chat_operators.py`, `showcase_operators.py`; properties in `properties.py`.
- Documented decisions: none beyond the shipped UI code.
- Governing owners: `draw_muse_panel`, `draw_chat_panel`, `draw_showcase_panel`; all operators keep their existing `bl_idname`s.
- Explicit exceptions: None documented.

## Findings (user-selected scope)
| # | Problem | Evidence | Proposed change | Scope | Confidence |
| --- | --- | --- | --- | --- | --- |
| 1 | Main panel has 7 stacked boxes (connection/generate/edit/material/geometry/history/cloud) | `panels.py` `_connection_box`…`_cloud_box` all drawn unconditionally | Merge into 4 boxes: Status, Create (variants), Library & Apply, Cloud Render | View3D + Shader + GN panels | High |
| 2 | Chat panel prints up to 24 wrapped messages, so the sidebar grows unboundedly | `draw_chat_panel` loops `muse_chat[-24:]` with `_wrap` | Show only the last assistant response; keep the full transcript in `muse_chat` data for the agent | Chat panel (View3D + Shader) | High |
| 3 | Generate vs Edit vs GN are three near-identical prompt/button boxes | `_generate_box`, `_edit_box`, per-object GN prompt | One Create box with a `create_mode` variant selector (Texture / Edit last / Geometry Nodes) | Main panel | High |
| 4 | Cloud render offers two buttons and no output-type choice; missing-token state does not tell the user what to put in `.env` | `_cloud_box`, `cloud_operators.MUSE_OT_cloud_render.mode` | One `output_type` selector (Image / Animation) + single Render button; missing creds show the exact `MODAL_TOKEN_ID=` / `MODAL_TOKEN_SECRET=` `.env` lines; chat quick action asks image-vs-animation and asks for the `.env` tokens when missing | Cloud box + chat | High |
| 5 | Chat uses one Spark model for everything | `properties.MuseAgentSettings.spark_model`, `chat_operators._start_llm` | Task routing: Blender tasks → lower model (`muse-spark-1.1`), site builds → higher model (`muse-spark-1.3`), Custom → manual `spark_model` | Chat panel + chat operators | Medium |

## Improve first
Finding 2 (chat length) — it is the panel the user lives in; last-response-only plus grouped quick actions makes every other workflow shorter to reach.
