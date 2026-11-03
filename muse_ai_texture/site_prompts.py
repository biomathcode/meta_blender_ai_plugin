"""Prompt improvement + e-commerce asset planning for the site harness.

Bpy-free and deterministic (no LLM call required) so it can be unit-tested
outside Blender and so "Improve Prompt" works offline. The Spark agent can
overwrite the result in the CMS afterwards — this step guarantees a usable,
commerce-shaped brief even when the user typed only a few words.

Pipeline position (showcase.build_website):
  Step 0  improve_prompt()   raw brief -> improved copy + image prompts
  Step 3  catalogue_views()  the Blender viewport angles every shop shows
  Step 4  spin plan          cloudimage-360 frames, one folder per finish
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Catalogue: the angles every e-commerce product page shows
# azimuth/elevation in degrees, distance = bbox-diagonal multiplier.
# ---------------------------------------------------------------------------

CATALOGUE_VIEWS: list[dict] = [
    {"id": "hero", "label": "Hero — front three-quarter",
     "azimuth": 35.0, "elevation": 18.0, "distance": 2.6,
     "file": "images/view_hero.jpg"},
    {"id": "front", "label": "Front",
     "azimuth": 0.0, "elevation": 12.0, "distance": 2.6,
     "file": "images/view_front.jpg"},
    {"id": "side", "label": "Side profile",
     "azimuth": 90.0, "elevation": 12.0, "distance": 2.6,
     "file": "images/view_side.jpg"},
    {"id": "back", "label": "Back",
     "azimuth": 180.0, "elevation": 14.0, "distance": 2.6,
     "file": "images/view_back.jpg"},
    {"id": "top", "label": "Top-down",
     "azimuth": 35.0, "elevation": 65.0, "distance": 2.8,
     "file": "images/view_top.jpg"},
    {"id": "detail", "label": "Detail — close-up",
     "azimuth": 55.0, "elevation": 24.0, "distance": 1.45,
     "file": "images/view_detail.jpg"},
]

# Finish name -> Principled Base Color (linear-ish RGB in 0..1). "Original"
# keeps the product's own materials untouched.
FINISH_PRESETS: dict[str, tuple[float, float, float] | None] = {
    "Original": None,
    "Matte Black": (0.03, 0.03, 0.035),
    "Arctic White": (0.92, 0.93, 0.95),
    "Forest Green": (0.08, 0.28, 0.14),
    "Ocean Blue": (0.05, 0.22, 0.48),
    "Sunset Orange": (0.85, 0.32, 0.08),
    "Crimson Red": (0.55, 0.05, 0.08),
}

_STYLE_WORDS = {
    "ECOMMERCE": ("clean studio product photography, seamless light background, "
                  "soft shadows, true colours, centred composition"),
    "STUDIO": ("editorial studio shot, dramatic softbox lighting, dark backdrop, "
               "premium product photography"),
    "LIFESTYLE": ("in-use lifestyle photography, natural light, real environment, "
                  "shallow depth of field, human scale cues"),
    "LUXURY": ("luxury campaign photography, dark elegant backdrop, rim light, "
               "reflective surface, generous negative space"),
}


def catalogue_views() -> list[dict]:
    return [dict(v) for v in CATALOGUE_VIEWS]


def parse_finishes(text: str) -> list[str]:
    """Comma list -> ordered unique finish names (Original always first)."""
    names: list[str] = []
    for part in re.split(r"[,;\n]", text or ""):
        name = " ".join(part.strip().split())
        if name and name not in names:
            names.append(name)
    if not names:
        return ["Original"]
    if "Original" in names:
        names.remove("Original")
    return ["Original"] + names


def finish_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "original").lower()).strip("-")
    return slug or "original"


def finish_color(name: str) -> tuple[float, float, float] | None:
    return FINISH_PRESETS.get(name)


def spin_plan(finish: str, frames: int) -> dict:
    """cloudimage-360 plan for one finish: folder + filename pattern."""
    frames = max(8, min(72, int(frames)))
    slug = finish_slug(finish)
    return {"finish": finish, "slug": slug,
            "folder": f"spin/{slug}/", "filename": "frame-{index}.jpg",
            "amount": frames}


def improve_prompt(raw: str, product_name: str = "", style: str = "ECOMMERCE",
                   audience: str = "") -> dict:
    """Expand a short brief into commerce copy + per-asset image prompts.

    Returns dict with improved brief, CMS-ready hero/story/feature copy,
    one generation prompt per asset kind, alt texts and SEO fields. The
    user's own words are kept as the lead — improvement adds structure,
    materials/finish language, lighting and composition, never invents a
    different product.
    """
    brief = " ".join((raw or "").strip().split())
    name = (product_name or "the product").strip() or "the product"
    style_key = (style or "ECOMMERCE").upper()
    if style_key not in _STYLE_WORDS:
        style_key = "ECOMMERCE"
    look = _STYLE_WORDS[style_key]
    lead = brief or f"{name}, shown exactly as modelled"
    if name.lower() not in lead.lower() and product_name:
        lead = f"{name} — {lead}"
    aud = f" for {audience.strip()}" if audience and audience.strip() else ""
    improved = (
        f"{lead}. Product photography brief: preserve the exact geometry, "
        f"proportions, materials and finish of the source model; {look}; "
        f"sharp focus on the product, no extra props covering it, no text, "
        f"no watermark, no people unless the brief asks for them. "
        f"Composition leaves negative space for the headline{aud}.")
    hero_title = f"Meet {name}." if product_name else "Meet the product."
    return {
        "improved": improved,
        "style": style_key,
        "hero_title": hero_title,
        "hero_subtitle": (
            f"{lead.rstrip('.')}. Photographed in Blender from every angle, "
            "explorable in interactive 3D — drag to orbit, scroll to explore."),
        "story_body": (
            f"Every curve of {name} was shaped in Blender, then photographed "
            "from the angles that matter — hero, front, side, back, top and a "
            "close detail — so what you see is the product, not a render trick."),
        "image_prompts": {
            "hero": f"{improved} Single hero shot, front three-quarter view.",
            "lifestyle": (f"{lead}. In-use lifestyle asset: the product in a "
                          f"believable real setting, natural light, human scale "
                          f"cues, product still the clear subject, no text."),
            "detail": (f"{lead}. Extreme close-up detail asset: materials, "
                       f"seams, edges and finish quality, macro product "
                       f"photography, raking light, no text."),
        },
        "alt_texts": {view["id"]: f"{name} — {view['label'].lower()}"
                      for view in CATALOGUE_VIEWS},
        "seo_title": f"{name} — 3D product showcase" if product_name else "3D product showcase",
        "seo_description": (
            f"Explore {name} in interactive 3D with a full photo catalogue "
            f"(hero, front, side, back, top, detail) and a 360° spin."),
    }


# ---------------------------------------------------------------------------
# Sketchfab-style product visualization setups (annotations, camera
# bookmarks, display modes, exploded view, AR) — data side, bpy-free.
# Researched from sketchfab.com/3d-viewer + /3d-ecommerce and the embed
# customization docs: annotations, turntable/autostart entrance, shading
# modes, environment, AR. Everything here runs locally (Three.js + GLB/
# USDZ), no Sketchfab hosting or account needed.
# ---------------------------------------------------------------------------

CAMERA_VIEWS: list[dict] = [
    {"id": "hero", "label": "Hero", "azimuth": 35.0, "elevation": 18.0},
    {"id": "front", "label": "Front", "azimuth": 0.0, "elevation": 12.0},
    {"id": "side", "label": "Side", "azimuth": 90.0, "elevation": 12.0},
    {"id": "back", "label": "Back", "azimuth": 180.0, "elevation": 14.0},
    {"id": "top", "label": "Top", "azimuth": 35.0, "elevation": 65.0},
]

DISPLAY_MODES: list[dict] = [
    {"id": "shaded", "label": "Shaded"},
    {"id": "wireframe", "label": "Wireframe"},
    {"id": "xray", "label": "X-Ray"},
    {"id": "clay", "label": "Clay"},
]


def parse_hotspots(text: str) -> list[dict]:
    """'Title::Body::azimuth,elevation; ...' -> annotation list.

    Azimuth/elevation place the marker on the product's bounding sphere
    (same convention as the catalogue cameras), so no 3D picking is
    needed in Blender — the web viewer projects the anchor each frame,
    Sketchfab-annotation style.
    """
    hotspots: list[dict] = []
    for chunk in re.split(r"[;\n]", text or ""):
        parts = [p.strip() for p in chunk.split("::")]
        if not parts or not parts[0]:
            continue
        azimuth, elevation = 35.0, 18.0
        if len(parts) >= 3 and "," in parts[2]:
            try:
                azimuth, elevation = (float(v) for v in parts[2].split(",", 1))
            except ValueError:
                pass
        hotspots.append({"title": parts[0],
                         "body": parts[1] if len(parts) >= 2 else "",
                         "azimuth": azimuth, "elevation": elevation})
    return hotspots


def build_shopify_product(product: dict, price: str = "", currency: str = "USD",
                          sku: str = "", vendor: str = "") -> dict:
    """Shopify-shaped product record (import JSON/CSV source of truth)."""
    name = product.get("name") or "Product"
    images = [{"src": img.get("file", ""), "alt": img.get("alt", "")}
              for img in product.get("images") or []]
    return {
        "title": name,
        "body_html": f"<p>{product.get('description') or ''}</p>",
        "vendor": vendor or "Muse Harness",
        "product_type": "3D Showcase",
        "status": "draft",
        "variants": [{"sku": sku or "", "price": str(price or "0.00"),
                      "inventory_management": None}],
        "images": images,
        "options": [],
        "currency": currency or "USD",
        "model3d": product.get("model") or "product.glb",
        "lods": product.get("lods") or {},
    }


def shopify_csv_row(product: dict, shopify: dict) -> dict:
    """One Shopify products.csv import row (header emitted by caller)."""
    variant = (shopify.get("variants") or [{}])[0]
    first_image = ((shopify.get("images") or [{}])[0]).get("src", "")
    handle = re.sub(r"[^a-z0-9]+", "-", (shopify.get("title") or "product").lower()).strip("-")
    return {
        "Handle": handle or "product",
        "Title": shopify.get("title") or "",
        "Body (HTML)": shopify.get("body_html") or "",
        "Vendor": shopify.get("vendor") or "",
        "Type": shopify.get("product_type") or "",
        "Status": shopify.get("status") or "draft",
        "Variant SKU": variant.get("sku", ""),
        "Variant Price": variant.get("price", ""),
        "Image Src": first_image,
        "Image Alt Text": ((shopify.get("images") or [{}])[0]).get("alt", ""),
        "3D Model": shopify.get("model3d") or "",
    }
