"""Operators for the Product Showcase workflow (panel buttons).

Steps: muse.optimize_selected -> muse.bake_product -> 
muse.create_showcase_animation -> CMS (muse.cms_*) -> muse.build_website
(+ muse.check_site_server / muse.open_site_url harness helpers). The heavy
lifting lives in showcase.py so the Muse agent tools call the identical
functions.
"""

from __future__ import annotations

import bpy
from bpy.types import Operator

from . import showcase, site_harness


class MUSE_OT_optimize_selected(Operator):
    bl_idname = "muse.optimize_selected"
    bl_label = "Create LODs (Low / Medium / High)"
    bl_description = ("Create three LOD versions of the selected mesh "
                      "(<name>_lod_high / _medium / _low). High keeps full "
                      "detail; the site lets visitors switch quality. "
                      "Original is kept")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        site = context.scene.muse_site
        try:
            result = showcase.create_lods(
                context, clean_first=site.clean_first)
        except RuntimeError as exc:
            site.status = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        tiers = ", ".join(
            f"{level} {info['faces']:,}" for level, info in result["lods"].items())
        site.status = (f"LODs from {result['source']} "
                       f"({result['faces_before']:,} faces): {tiers}. "
                       "Original kept. Next: bake detail (Medium/Low), "
                       "then create the animation.")
        self.report({"INFO"}, site.status)
        return {"FINISHED"}


class MUSE_OT_bake_product(Operator):
    bl_idname = "muse.bake_product"
    bl_label = "Bake Detail onto Medium / Low LODs"
    bl_description = ("Bake Normal + AO from the original mesh onto the "
                      "Medium and Low LODs (High keeps full detail) — run "
                      "before rendering or building the GLBs")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        site = context.scene.muse_site
        try:
            result = showcase.bake_lod_maps(context)
        except RuntimeError as exc:
            site.status = str(exc)
            site.bake_status = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        site.status = result.get("detail") or f"Baked onto {result['object']}."
        self.report({"INFO"}, site.status)
        return {"FINISHED"}


class MUSE_OT_create_showcase_animation(Operator):
    bl_idname = "muse.create_showcase_animation"
    bl_label = "Create Showcase Animation"
    bl_description = "Bake a turntable animation (exported in the GLB, scrubbed by scroll on the site)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        site = context.scene.muse_site
        try:
            result = showcase.create_showcase_animation(
                context, style=site.animation_style, frames=site.animation_frames)
        except RuntimeError as exc:
            site.status = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        site.status = (f"Animation '{result['animation']}' baked on {result['object']} "
                       f"({result['frames']} frames). Next: edit the CMS, then Build Website.")
        self.report({"INFO"}, site.status)
        return {"FINISHED"}


class MUSE_OT_cms_seed(Operator):
    bl_idname = "muse.cms_seed"
    bl_label = "Seed Default CMS Content"
    bl_description = "Add the default languages (en + hi) and showcase copy (existing text is kept)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        site = context.scene.muse_site
        obj = showcase.product_object(context)
        result = showcase.seed_cms(
            context, site.brand_name or site.product_object
            or (obj.name.removesuffix("_web") if obj else ""))
        showcase.ensure_translation_slots(context)
        site.status = (f"CMS ready: {result['languages']} languages, "
                       f"{result['entries']} entries. Edit any text below.")
        self.report({"INFO"}, site.status)
        return {"FINISHED"}


class MUSE_OT_cms_add_language(Operator):
    bl_idname = "muse.cms_add_language"
    bl_label = "Add Language"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        site = scene.muse_site
        code = site.new_language_code.strip().lower()
        if not code:
            self.report({"ERROR"}, "Type a language code first (e.g. es, fr, de).")
            return {"CANCELLED"}
        if any(lang.code == code for lang in scene.muse_site_languages):
            self.report({"ERROR"}, f"Language '{code}' already exists.")
            return {"CANCELLED"}
        lang = scene.muse_site_languages.add()
        lang.code = code
        lang.label = site.new_language_label.strip() or code
        lang.is_default = not scene.muse_site_languages
        showcase.ensure_translation_slots(context)
        site.status = (f"Language '{code}' added. Fill its translations per entry "
                       "(blank = default-language fallback on the site).")
        self.report({"INFO"}, site.status)
        return {"FINISHED"}


class MUSE_OT_cms_remove_language(Operator):
    bl_idname = "muse.cms_remove_language"
    bl_label = "Remove Language"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        index = scene.muse_site.language_index
        if not (0 <= index < len(scene.muse_site_languages)):
            self.report({"ERROR"}, "Select a language first.")
            return {"CANCELLED"}
        removed = scene.muse_site_languages[index].code
        scene.muse_site_languages.remove(index)
        scene.muse_site.language_index = max(0, index - 1)
        scene.muse_site.status = f"Language '{removed}' removed (its translations stay but are unused)."
        return {"FINISHED"}


class MUSE_OT_cms_set_default_language(Operator):
    bl_idname = "muse.cms_set_default_language"
    bl_label = "Make Default"
    bl_description = "The default language is the site fallback for missing translations"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        index = scene.muse_site.language_index
        if not (0 <= index < len(scene.muse_site_languages)):
            self.report({"ERROR"}, "Select a language first.")
            return {"CANCELLED"}
        for i, lang in enumerate(scene.muse_site_languages):
            lang.is_default = i == index
        scene.muse_site.status = f"'{scene.muse_site_languages[index].code}' is now the default (fallback) language."
        return {"FINISHED"}


class MUSE_OT_cms_add_entry(Operator):
    bl_idname = "muse.cms_add_entry"
    bl_label = "Add Entry"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        site = scene.muse_site
        key = site.new_entry_key.strip()
        if not key:
            self.report({"ERROR"}, "Type an entry key first.")
            return {"CANCELLED"}
        if any(e.key == key for e in scene.muse_site_entries):
            self.report({"ERROR"}, f"Entry '{key}' already exists.")
            return {"CANCELLED"}
        entry = scene.muse_site_entries.add()
        entry.key = key
        entry.section = site.new_entry_section.strip() or "Custom"
        showcase.ensure_translation_slots(context)
        site.entry_index = len(scene.muse_site_entries) - 1
        site.status = f"Entry '{key}' added. Custom keys are exported in content.json/locales."
        return {"FINISHED"}


class MUSE_OT_cms_remove_entry(Operator):
    bl_idname = "muse.cms_remove_entry"
    bl_label = "Remove Entry"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        index = scene.muse_site.entry_index
        if not (0 <= index < len(scene.muse_site_entries)):
            self.report({"ERROR"}, "Select an entry first.")
            return {"CANCELLED"}
        removed = scene.muse_site_entries[index].key
        scene.muse_site_entries.remove(index)
        scene.muse_site.entry_index = max(0, index - 1)
        scene.muse_site.status = f"Entry '{removed}' removed."
        return {"FINISHED"}


class MUSE_OT_improve_site_prompt(Operator):
    bl_idname = "muse.improve_site_prompt"
    bl_label = "Improve Prompt"
    bl_description = ("Step 0: expand your short brief into commerce copy, "
                      "hero/lifestyle/detail image prompts and alt texts")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        site = context.scene.muse_site
        result = showcase.improve_site_prompt(context)
        site.status = site.prompt_status
        self.report({"INFO"}, f"Improved prompt ({result['style']}): {result['improved'][:120]}…")
        return {"FINISHED"}


class MUSE_OT_render_catalogue(Operator):
    bl_idname = "muse.render_catalogue"
    bl_label = "Render Catalogue Images"
    bl_description = ("Render hero/front/side/back/top/detail JPGs in Blender "
                      "into the website images/ folder")
    bl_options = {"REGISTER"}

    def execute(self, context):
        site = context.scene.muse_site
        try:
            images = showcase.render_catalogue_images(
                context, showcase.website_dir(context))
        except Exception as exc:  # noqa: BLE001
            site.status = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        site.status = (f"Catalogue rendered: {len(images)} images "
                       f"({', '.join(i['id'] for i in images)}).")
        self.report({"INFO"}, site.status)
        return {"FINISHED"}


class MUSE_OT_render_spin(Operator):
    bl_idname = "muse.render_spin"
    bl_label = "Render 360° Spin (per finish)"
    bl_description = ("Render cloudimage-360 frame folders in Blender — one "
                      "spin per configurator finish")
    bl_options = {"REGISTER"}

    def execute(self, context):
        site = context.scene.muse_site
        try:
            spins = showcase.render_spin_images(
                context, showcase.website_dir(context))
        except Exception as exc:  # noqa: BLE001
            site.status = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        site.status = (f"360° spins rendered: "
                       f"{', '.join(s['finish'] for s in spins)} "
                       f"({site.spin_frames} frames each).")
        self.report({"INFO"}, site.status)
        return {"FINISHED"}


class MUSE_OT_build_website(Operator):
    bl_idname = "muse.build_website"
    bl_label = "Build Website"
    bl_description = ("Improve prompt → bake → LOD GLBs → Blender catalogue/360 "
                      "renders → site for the chosen category (Showcase / "
                      "Shopify store / 360° Configurator) with CMS baked in")
    bl_options = {"REGISTER"}

    def execute(self, context):
        site = context.scene.muse_site
        try:
            result = showcase.build_website(context)
        except RuntimeError as exc:
            site.status = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        problems = result.get("validation") or []
        site.status = (f"{result.get('variant', 'SHOWCASE')} website built in {result['site_dir']} "
                       f"(GLB {result['glb_kb']} KB, {len(result.get('images') or [])} catalogue images, "
                       f"{len(result.get('spins') or [])} 360° spins, "
                       f"{result['languages']} languages, "
                       f"{result['entries']} CMS entries, animation: "
                       f"{result['animation'] or 'none'}). "
                       f"{'Harness OK. ' if not problems else 'Harness problems: ' + '; '.join(problems) + '. '}"
                       f"{'● LIVE at ' + result['url'] if result.get('running') else '○ Not serving yet — run: ' + site_harness.serve_command(result['site_dir'], result['port'])}")
        self.report({"INFO"}, site.status)
        return {"FINISHED"}


class MUSE_OT_open_website_folder(Operator):
    bl_idname = "muse.open_website_folder"
    bl_label = "Open Website Folder"

    def execute(self, context):
        bpy.ops.wm.path_open(filepath=showcase.website_dir(context))
        return {"FINISHED"}


class MUSE_OT_check_site_server(Operator):
    bl_idname = "muse.check_site_server"
    bl_label = "Check If Site Is Running"
    bl_description = "Probe the showcase port and report the live URL"

    def execute(self, context):
        site = context.scene.muse_site
        port = site_harness.find_free_port(int(site.site_port or 8000)) \
            if not site_harness.is_port_listening(int(site.site_port or 8000)) \
            else int(site.site_port or 8000)
        # Probe the preferred port first (our server may already be there).
        probe = site_harness.probe_site(int(site.site_port or 8000), showcase.website_dir(context))
        if probe["is_showcase"]:
            site.status = f"● Site is LIVE at {probe['url']} — open it in your browser."
        elif probe["running"]:
            alt = site_harness.probe_site(port, showcase.website_dir(context))
            site.status = (f"○ Port {site.site_port} serves other content; "
                           f"showcase would use {alt['url']}. Run: "
                           f"{site_harness.serve_command(showcase.website_dir(context), port)}")
            probe = alt
        else:
            site.status = (f"○ Site is not running. Start it: "
                           f"{site_harness.serve_command(showcase.website_dir(context), int(site.site_port or 8000))} "
                           f"then open http://127.0.0.1:{int(site.site_port or 8000)}/")
        self.report({"INFO"}, site.status)
        return {"FINISHED"}


class MUSE_OT_open_site_url(Operator):
    bl_idname = "muse.open_site_url"
    bl_label = "Open Site in Browser"
    bl_description = "Open the live showcase URL (preferred port) in the default browser"

    def execute(self, context):
        site = context.scene.muse_site
        url = f"http://127.0.0.1:{int(site.site_port or 8000)}/"
        bpy.ops.wm.url_open(url=url)
        site.status = f"Opened {url} in your browser (if the server is running)."
        return {"FINISHED"}


classes = (MUSE_OT_improve_site_prompt, MUSE_OT_render_catalogue,
           MUSE_OT_render_spin,
           MUSE_OT_optimize_selected, MUSE_OT_bake_product,
           MUSE_OT_create_showcase_animation,
           MUSE_OT_cms_seed, MUSE_OT_cms_add_language, MUSE_OT_cms_remove_language,
           MUSE_OT_cms_set_default_language, MUSE_OT_cms_add_entry,
           MUSE_OT_cms_remove_entry, MUSE_OT_build_website,
           MUSE_OT_open_website_folder, MUSE_OT_check_site_server,
           MUSE_OT_open_site_url)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
