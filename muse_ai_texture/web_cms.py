"""In-Blender CMS + i18n layer for the Three.js product showcase (bpy-free).

The CMS lives *inside Blender* (Scene PropertyGroups in properties.py):
languages, content entries, and one translation per language per entry.
This module holds the pure data logic — seed content, locale building with
default-language fallback, and site-data assembly — so it can be unit-tested
outside Blender. The Blender side converts PropertyGroups to/from the plain
dicts used here:

    languages = [{"code": "en", "label": "English", "is_default": True}, ...]
    entries   = [{"key": "hero_title", "section": "Hero",
                  "translations": {"en": "...", "hi": "..."}}, ...]
"""

from __future__ import annotations

# (key, section, English text, Hindi text or "")
SEED_ENTRIES: list[tuple[str, str, str, str]] = [
    ("brand", "Global", "Muse Product", "Muse उत्पाद"),
    ("nav_story", "Global", "Story", "कहानी"),
    ("nav_features", "Global", "Features", "विशेषताएं"),
    ("nav_specs", "Global", "Specs", "विनिर्देश"),
    ("hero_kicker", "Hero", "Crafted in Blender · Showcased on the web", "Blender में निर्मित · वेब पर प्रदर्शित"),
    ("hero_title", "Hero", "Meet the product.", "उत्पाद से मिलिए।"),
    ("hero_subtitle", "Hero",
     "Optimized in Blender, animated for the web, and presented with a "
     "scroll-driven Three.js showcase. Drag to orbit — scroll to explore.",
     "Blender में अनुकूलित, वेब के लिए एनिमेटेड, और स्क्रॉल-चालित Three.js "
     "शोकेस के साथ प्रस्तुत। घुमाने के लिए खींचें — देखने के लिए स्क्रॉल करें।"),
    ("hero_cta", "Hero", "Explore", "देखें"),
    ("story_title", "Story", "Built to be looked at.", "देखे जाने के लिए बना।"),
    ("story_body", "Story",
     "Every curve was shaped by hand, then decimated and cleaned for the "
     "web so it loads fast and still looks like itself.",
     "हर वक्र हाथ से बनाया गया, फिर वेब के लिए साफ़ और हल्का किया गया — "
     "ताकि यह तेज़ी से लोड हो और फिर भी वैसा ही दिखे।"),
    ("feature_1_title", "Features", "Web-optimized mesh", "वेब-अनुकूलित मेश"),
    ("feature_1_body", "Features",
     "Decimated and cleaned in Blender before export — fewer faces, same silhouette.",
     "निर्यात से पहले Blender में हल्का और साफ़ — कम फेस, वही आकार।"),
    ("feature_2_title", "Features", "Scroll-driven animation", "स्क्रॉल-चालित एनिमेशन"),
    ("feature_2_body", "Features",
     "The turntable animation baked in Blender is scrubbed by GSAP ScrollTrigger as you scroll.",
     "Blender में बेक किया गया टर्नटेबल एनिमेशन स्क्रॉल के साथ चलता है।"),
    ("feature_3_title", "Features", "Speaks your language", "आपकी भाषा बोलता है"),
    ("feature_3_body", "Features",
     "All copy lives in the Blender CMS. Switch languages above — missing "
     "translations fall back to the default language.",
     "सारा टेक्स्ट Blender CMS में है। ऊपर भाषा बदलें — गायब अनुवाद "
     "डिफ़ॉल्ट भाषा में दिखेगा।"),
    ("specs_title", "Specs", "Under the hood", "अंदर की बात"),
    ("specs_body", "Specs",
     "Exported as a single GLB with its animation. Face counts before and "
     "after optimization are shown in the Blender Showcase panel.",
     "अपने एनिमेशन के साथ एक ही GLB में निर्यातित। अनुकूलन से पहले और "
     "बाद के फेस Blender शोकेस पैनल में दिखते हैं।"),
    ("cta_title", "CTA", "Ready when you are.", "जब आप तैयार हों।"),
    ("cta_body", "CTA",
     "Rebuild this site from Blender after any CMS edit: "
     "Showcase panel → Build Website.",
     "किसी भी CMS बदलाव के बाद Blender से साइट फिर बनाएँ: "
     "शोकेस पैनल → Build Website।"),
    ("cta_button", "CTA", "Back to top", "ऊपर जाएँ"),
    ("footer_text", "Global", "Made with Muse Harness for Blender.", "Blender के लिए Muse Harness से निर्मित।"),
]

SEED_LANGUAGES: list[tuple[str, str, bool]] = [
    ("en", "English", True),
    ("hi", "हिन्दी (Hindi)", False),
]


def seed_entries(product_name: str = "") -> list[dict]:
    """Default CMS entries; `hero_title` is personalised when a name is given."""
    entries = []
    for key, section, en, hi in SEED_ENTRIES:
        if key == "hero_title" and product_name:
            en = f"Meet {product_name}."
            hi = f"{product_name} से मिलिए।"
        if key == "brand" and product_name:
            en = product_name
            hi = product_name
        entries.append({"key": key, "section": section,
                        "translations": {"en": en, "hi": hi}})
    return entries


def seed_languages() -> list[dict]:
    return [{"code": code, "label": label, "is_default": is_default}
            for code, label, is_default in SEED_LANGUAGES]


def default_language(languages: list[dict]) -> str:
    for lang in languages:
        if lang.get("is_default") and lang.get("code"):
            return lang["code"]
    return languages[0]["code"] if languages else "en"


def build_locale(entries: list[dict], lang: str, default_lang: str) -> dict[str, str]:
    """One locale dict for `lang`, falling back to the default language.

    Fallback order per key: requested language -> default language -> any
    non-empty translation -> the key itself (never an empty string on site).
    """
    locale: dict[str, str] = {}
    for entry in entries:
        translations = entry.get("translations") or {}
        text = (translations.get(lang) or "").strip()
        if not text:
            text = (translations.get(default_lang) or "").strip()
        if not text:
            text = next((v.strip() for v in translations.values() if v.strip()), entry["key"])
        locale[entry["key"]] = text
    return locale


def build_locales(entries: list[dict], languages: list[dict]) -> dict[str, dict[str, str]]:
    default_lang = default_language(languages)
    return {lang["code"]: build_locale(entries, lang["code"], default_lang)
            for lang in languages if lang.get("code")}


def missing_translations(entries: list[dict], languages: list[dict]) -> dict[str, list[str]]:
    """Map language code -> entry keys with no text (they will fall back)."""
    default_lang = default_language(languages)
    missing: dict[str, list[str]] = {}
    for lang in languages:
        code = lang.get("code", "")
        if not code or code == default_lang:
            continue
        absent = [e["key"] for e in entries
                  if not (e.get("translations") or {}).get(code, "").strip()]
        if absent:
            missing[code] = absent
    return missing


def build_site_data(product: dict, languages: list[dict], entries: list[dict],
                    config: dict) -> dict:
    """Assemble the JSON embedded in the generated site (and content.json)."""
    return {
        "product": product,
        "languages": [{"code": l["code"], "label": l.get("label", l["code"])}
                      for l in languages if l.get("code")],
        "defaultLanguage": default_language(languages),
        "locales": build_locales(entries, languages),
        "missingTranslations": missing_translations(entries, languages),
        "config": config,
    }
