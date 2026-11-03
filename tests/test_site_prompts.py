"""Tests for site_prompts + variant templates + harness (bpy-free)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "muse_ai_texture"))
import site_prompts as sp
import site_template, site_harness, json, tempfile, pathlib

def test_improve():
    r = sp.improve_prompt("handmade ceramic vase, matte glaze", product_name="Aura Vase")
    assert "Aura Vase" in r["improved"] and "handmade ceramic vase" in r["improved"]
    assert set(r["image_prompts"]) == {"hero","lifestyle","detail"}
    assert r["alt_texts"]["hero"].startswith("Aura Vase")
    r2 = sp.improve_prompt("", product_name="")
    assert "the product" in r2["improved"]

def test_catalogue_and_finishes():
    views = sp.catalogue_views()
    assert [v["id"] for v in views] == ["hero","front","side","back","top","detail"]
    assert sp.parse_finishes("Matte Black, Original, Matte Black, Ocean Blue") == ["Original","Matte Black","Ocean Blue"]
    assert sp.parse_finishes("") == ["Original"]
    assert sp.finish_color("Original") is None and sp.finish_color("Ocean Blue") is not None
    plan = sp.spin_plan("Matte Black", 24)
    assert plan == {"finish":"Matte Black","slug":"matte-black","folder":"spin/matte-black/","filename":"frame-{index}.jpg","amount":24}

def test_shopify():
    prod = {"name":"Aura Vase","model":"product.glb","images":[{"file":"images/view_hero.jpg","alt":"hero"}]}
    shop = sp.build_shopify_product(prod, price="49.00", sku="VASE-1")
    assert shop["title"]=="Aura Vase" and shop["variants"][0]["price"]=="49.00"
    row = sp.shopify_csv_row(prod, shop)
    assert row["Handle"]=="aura-vase" and row["Image Src"]=="images/view_hero.jpg"

def test_templates():
    data = json.dumps({"product":{"name":"Vase","images":[],"spins":[],"finishes":["Original"]},"config":{},"locales":{}})
    shop = site_template.render_site_html(data, variant="SHOPIFY")
    assert "cloudimage-360" in shop and "Add to cart" in shop and "__SITE_DATA__" not in shop
    conf = site_template.render_site_html(data, variant="CONFIGURATOR")
    assert "cloudimage-360" in conf and "Finish" in conf and "__VIEWER_JS__" not in conf
    show = site_template.render_site_html(data, variant="SHOWCASE")
    assert "site-data" in show

def test_harness_validation():
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        (td/"product.glb").write_bytes(b"glTF" + b"x"*200)
        (td/"index.html").write_text('<script id="site-data">{}</script> three')
        product={"variant":"CONFIGURATOR","images":[{"file":"images/view_hero.jpg"}],"spins":[{"folder":"spin/original/","amount":2}]}
        (td/"content.json").write_text(json.dumps({"locales":{},"product":product}))
        problems = site_harness.validate_site(str(td))
        assert any("catalogue image missing" in p for p in problems), problems
        assert any("360 frame missing" in p for p in problems), problems
        (td/"images").mkdir(); (td/"images/view_hero.jpg").write_bytes(b"x")
        (td/"spin/original").mkdir(parents=True)
        (td/"spin/original/frame-1.jpg").write_bytes(b"x"); (td/"spin/original/frame-2.jpg").write_bytes(b"x")
        assert site_harness.validate_site(str(td)) == [], site_harness.validate_site(str(td))


def test_hotspots_and_modes():
    hs = sp.parse_hotspots("Finish::Matte glaze::35,18; Scale::True size::120,14; Bad")
    assert hs[0] == {"title":"Finish","body":"Matte glaze","azimuth":35.0,"elevation":18.0}
    assert hs[2]["title"]=="Bad" and hs[2]["azimuth"]==35.0
    assert [m["id"] for m in sp.DISPLAY_MODES] == ["shaded","wireframe","xray","clay"]
    assert [v["id"] for v in sp.CAMERA_VIEWS] == ["hero","front","side","back","top"]
    data = json.dumps({"product":{"name":"V","images":[],"spins":[],"finishes":["Original"],
      "hotspots":hs,"cameraViews":sp.CAMERA_VIEWS,"displayModes":sp.DISPLAY_MODES},"config":{},"locales":{}})
    html = site_template.render_site_html(data, variant="CONFIGURATOR")
    for needle in ("vtoolbar","hotspot","Explode","Fullscreen","Screenshot","View in AR" if False else "flyTo"):
        assert needle in html, needle

if __name__ == "__main__":
    test_improve(); test_catalogue_and_finishes(); test_shopify(); test_templates(); test_harness_validation(); test_hotspots_and_modes()
    print("test_site_prompts: OK")
