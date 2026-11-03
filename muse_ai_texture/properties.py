"""Scene / Object properties and generation history for Muse Harness."""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


class MuseHistoryItem(PropertyGroup):
    name: StringProperty(name="Name")
    prompt: StringProperty(name="Prompt")
    filepath: StringProperty(name="File")
    image_name: StringProperty(name="Image")
    created: StringProperty(name="Created")


class MuseSceneSettings(PropertyGroup):
    create_mode: EnumProperty(
        name="Create",
        description="What the Create box does (variants of the same Muse Image flow)",
        items=[
            ("TEXTURE", "Texture", "Generate a new texture from a prompt"),
            ("EDIT", "Edit Last", "Re-prompt the last generated image"),
            ("GN", "Geometry Nodes", "Generate and feed the Muse GN Texture modifier"),
        ],
        default="TEXTURE",
    )
    prompt: StringProperty(
        name="Prompt",
        description="Describe the texture or image for Muse Image 1.0",
        default="weathered red brick wall with subtle moss",
    )
    edit_prompt: StringProperty(
        name="Edit Prompt",
        description="Change to apply on top of the last generated image",
        default="make it older, add cracks and darker stains",
    )
    size: EnumProperty(
        name="Size",
        description="Output size (aspect hint for Muse Image)",
        items=[
            ("1024x1024", "Square 1024×1024", ""),
            ("1536x1024", "Landscape 1536×1024", ""),
            ("1024x1536", "Portrait 1024×1536", ""),
        ],
        default="1024x1024",
    )
    style: EnumProperty(
        name="Style",
        items=[
            ("PBR_TEXTURE", "PBR Texture", "Tileable material texture"),
            ("PHOTOREAL", "Photoreal", "Photoreal surface"),
            ("HAND_PAINTED", "Hand-painted", "Stylised game texture"),
            ("PIXEL_ART", "Pixel Art", "Pixel-art texture"),
            ("NONE", "None", "Use the prompt as-is"),
        ],
        default="PBR_TEXTURE",
    )
    tileable: BoolProperty(name="Seamless / Tileable", default=True)
    auto_apply: BoolProperty(
        name="Apply to Selected Object",
        description="Create/update a material on the active mesh after generating",
        default=True,
    )
    use_bump: BoolProperty(name="Derive Bump", default=True)
    use_roughness: BoolProperty(name="Derive Roughness Variation", default=True)
    status: StringProperty(name="Status", default="Ready. Set a prompt and generate.")
    is_generating: BoolProperty(name="Generating", default=False)
    history_index: bpy.props.IntProperty(name="History Index", default=-1)


class MuseObjectSettings(PropertyGroup):
    gn_prompt: StringProperty(
        name="GN Prompt",
        description="Prompt used when generating a texture for this object's "
                    "Geometry Nodes modifier",
        default="rocky cliff surface with strata and pebbles",
    )
    gn_tileable: BoolProperty(name="GN Tileable", default=True)


class MuseChatMessage(PropertyGroup):
    role: StringProperty(name="Role")  # user | assistant | tool | system
    text: StringProperty(name="Text")


class MuseAgentSettings(PropertyGroup):
    task_type: EnumProperty(
        name="Task",
        description="Routes the chat to a model tier: fast model for Blender "
                    "work, best model for website builds",
        items=[
            ("BLENDER", "Blender Task", "Build, texture, light, optimize, render — lower Spark model"),
            ("SITE", "Website / Showcase", "Product showcase site build — higher Spark model"),
            ("CUSTOM", "Custom Model", "Use the Agent Model chosen below"),
        ],
        default="BLENDER",
    )
    input_text: StringProperty(
        name="Message",
        description="Tell the Muse Spark agent what to do in Blender",
        default="",
    )
    spark_model: EnumProperty(
        name="Agent Model",
        description="Meta Muse Spark model driving the agent",
        items=[
            ("muse-spark-1.3", "Muse Spark 1.3", "Recommended"),
            ("muse-spark-1.2", "Muse Spark 1.2", ""),
            ("muse-spark-1.1", "Muse Spark 1.1", ""),
        ],
        default="muse-spark-1.3",
    )
    max_iterations: bpy.props.IntProperty(
        name="Max Steps", default=12, min=1, max=40,
        description="Maximum tool-calling rounds per request")
    allow_code_execution: bpy.props.BoolProperty(
        name="Allow Python Execution",
        description="Let the agent run arbitrary bpy code (execute_blender_python) "
                    "for actions structured tools don't cover",
        default=True,
    )
    prefer_mcp: bpy.props.BoolProperty(
        name="Prefer Blender MCP Socket",
        description="When running outside Blender, route code via the Blender "
                    "MCP server on port 9876 (inside Blender, in-process "
                    "execution is used to avoid main-thread deadlock)",
        default=False,
    )
    status: StringProperty(name="Agent Status", default="Ready. Ask me to build, texture, optimize…")
    is_running: bpy.props.BoolProperty(name="Agent Running", default=False)
    stop_requested: bpy.props.BoolProperty(name="Stop Requested", default=False)
    mcp_status: StringProperty(name="MCP Status", default="Blender MCP: not checked yet.")
    chat_index: bpy.props.IntProperty(name="Chat Index", default=-1)


class MuseCloudSettings(PropertyGroup):
    output_type: EnumProperty(
        name="Output",
        description="What Modal renders from the scene camera",
        items=[
            ("STILL", "Image", "Single frame PNG from the active camera"),
            ("ANIMATION", "Animation / Video", "Frame range rendered in parallel, stitched to MP4"),
        ],
        default="STILL",
    )
    use_gpu: bpy.props.BoolProperty(
        name="Use GPU (Cycles)",
        description="Render on a Modal GPU (Cycles CUDA, CPU fallback inside "
                    "the container). Off = render on many CPUs instead",
        default=True,
    )
    gpu: EnumProperty(
        name="GPU",
        items=[(name, name, "") for name in
               ("L40S", "L4", "A10G", "T4", "A100", "H100")],
        default="L40S",
    )
    max_containers: bpy.props.IntProperty(
        name="Max Containers", default=10, min=1, max=100,
        description="Parallel Modal containers for animation frames")
    frame_step: bpy.props.IntProperty(
        name="Frame Step", default=1, min=1, max=100,
        description="Render every Nth frame for animations")
    status: StringProperty(
        name="Cloud Status",
        default="Ready. Set a camera, then render the viewport in the cloud.")
    is_rendering: bpy.props.BoolProperty(name="Cloud Rendering", default=False)
    last_result: StringProperty(name="Last Cloud Result", default="")


class MuseSplatSettings(PropertyGroup):
    """Gaussian Splat: SAM 3.1 (Meta Model API) segmentation -> objects.

    One click exports the active splat's points, renders orbit views,
    segments exactly the objects typed below with SAM 3.1 on the Meta
    Model API (same Meta key as Muse Image), votes the masks back onto
    the Gaussians, and splits them into separate native splat objects
    with Blender's point delete/separate (Geometry Nodes). Nothing else
    is segmented — there is no automatic / everything mode.
    """
    spz_path: StringProperty(
        name="SPZ File",
        description="Gaussian splat .spz to import (or use the active "
                    "PointCloud splat object directly)",
        default="", subtype="FILE_PATH")
    source_object: StringProperty(
        name="Splat Object",
        description="PointCloud object to segment (blank = active object)",
        default="")
    prompts: StringProperty(
        name="Objects to Segment",
        description="Comma-separated objects for SAM 3.1, e.g. "
                    "'sand, rock, shell'. Only these objects are "
                    "segmented — one Meta API request each per view",
        default="sand, rock, shell, vegetation")
    num_views: bpy.props.IntProperty(
        name="Views", default=16, min=6, max=32,
        description="Orbit views rendered and segmented (more = cleaner "
                    "votes, slower). 16 is the sweet spot for one splat")
    resolution: EnumProperty(
        name="View Size",
        description="Rendered view size sent to SAM 3.1 (API cost scales with pixels)",
        items=[("512", "512", ""), ("768", "768", ""), ("1024", "1024", "")],
        default="1024")
    sam_threshold: FloatProperty(
        name="SAM Threshold", default=0.5, min=0.05, max=0.95,
        description="Minimum SAM 3.1 confidence kept from the Meta API "
                    "(lower finds more, noisier)")
    min_votes: bpy.props.IntProperty(
        name="Min Votes", default=2, min=1, max=8,
        description="A Gaussian needs this many agreeing views to take a label")
    min_cluster: bpy.props.IntProperty(
        name="Min Points / Object", default=800, min=10, max=200000,
        description="Smaller same-concept clusters fall back to the "
                    "background object instead of becoming tiny objects")
    keep_background: BoolProperty(
        name="Keep Background Object",
        description="Keep unlabelled Gaussians as a '*_background' splat "
                    "object (nothing is ever deleted)",
        default=True)
    status: StringProperty(
        name="Splat Status",
        default="Import an .spz, type the objects to segment, then Segment & Separate.")
    is_processing: BoolProperty(name="Segmenting", default=False)
    last_workdir: StringProperty(name="Last Work Folder", default="")
    last_summary: StringProperty(name="Last Summary", default="")


class MuseSiteTranslation(PropertyGroup):
    lang: StringProperty(name="Language Code")
    text: StringProperty(name="Text", default="")


class MuseSiteLanguage(PropertyGroup):
    code: StringProperty(name="Code", description="ISO code, e.g. en, hi, es", default="en")
    label: StringProperty(name="Label", description="Shown in the site language switcher", default="English")
    is_default: BoolProperty(name="Default", description="Fallback language on the site", default=False)


class MuseSiteEntry(PropertyGroup):
    key: StringProperty(name="Key", description="CMS key used by the site template, e.g. hero_title")
    section: StringProperty(name="Section", default="Hero")
    translations: CollectionProperty(type=MuseSiteTranslation)


class MuseSiteSettings(PropertyGroup):
    """Product Showcase: prompt -> LODs -> bake -> animate -> catalogue/360
    renders -> CMS (i18n) -> Three.js site (Showcase / Shopify / Configurator)."""
    site_variant: EnumProperty(
        name="Site Category",
        description="Which website the harness builds from the same product: "
                    "scroll Showcase, Shopify-style store product page, or "
                    "360° Configurator (Blender spin images per finish)",
        items=[
            ("SHOWCASE", "Showcase (scroll 3D)", "GSAP scroll showcase with interactive Three.js viewer"),
            ("SHOPIFY", "Shopify Store", "Store product page: gallery + 3D viewer, price, buy panel, Shopify import files"),
            ("CONFIGURATOR", "Configurator (360°)", "Pick a finish, spin the product 360° (Blender-rendered frames, cloudimage-360 viewer)"),
        ],
        default="SHOWCASE")
    # --- Step 0: prompt improvement (deterministic, offline) ---
    prompt_raw: StringProperty(
        name="Your Brief",
        description="Short product brief, e.g. 'handmade ceramic vase, matte glaze'. "
                    "Improve Prompt expands it into commerce copy + image prompts",
        default="")
    prompt_style: EnumProperty(
        name="Prompt Style",
        items=[("ECOMMERCE", "E-commerce", ""), ("STUDIO", "Studio", ""),
               ("LIFESTYLE", "Lifestyle", ""), ("LUXURY", "Luxury", "")],
        default="ECOMMERCE")
    prompt_audience: StringProperty(
        name="Audience", description="Who it is for, e.g. 'home brewers' (optional)", default="")
    prompt_improved: StringProperty(name="Improved Prompt", default="")
    prompt_status: StringProperty(name="Prompt Status", default="")
    generate_ai_assets: BoolProperty(
        name="Generate AI Image Assets",
        description="Also generate hero/lifestyle/detail stills with Muse Image "
                    "from the improved prompts (catalogue renders always come from Blender)",
        default=False)
    # --- Catalogue + 360 renders (Blender viewport/camera renders) ---
    render_catalogue: BoolProperty(
        name="Render Catalogue Images",
        description="Render hero/front/side/back/top/detail JPGs in Blender into images/",
        default=True)
    render_360: BoolProperty(
        name="Render 360° Spin",
        description="Render the cloudimage-360 frame sequence in Blender (spin/<finish>/)",
        default=True)
    spin_frames: bpy.props.IntProperty(
        name="360 Frames", default=24, min=8, max=72,
        description="Frames per full 360° spin (24 is the e-commerce sweet spot)")
    image_resolution: EnumProperty(
        name="Image Size",
        items=[("512", "512", ""), ("1024", "1024", ""), ("2048", "2048", "")],
        default="1024")
    finish_options: StringProperty(
        name="Finishes",
        description="Configurator finishes, comma-separated. Known names "
                    "(Matte Black, Arctic White, Forest Green, Ocean Blue, "
                    "Sunset Orange, Crimson Red) tint the product; Original "
                    "keeps its own materials. First finish is the default",
        default="Original, Matte Black, Arctic White")
    # --- Sketchfab-style visualization (annotations / AR / viewer) ---
    hotspots: StringProperty(
        name="Hotspots",
        description="Viewer annotations, separated by ';' — format "
                    "'Title::Description::azimuth,elevation' e.g. "
                    "'Finish::Matte ceramic glaze::35,18'. Markers ride the "
                    "model in the web viewer; click one to fly there",
        default="Crafted finish::Materials and finish, true to the model::35,18; "
                "True proportions::Shown at real scale from every side::120,14")
    enable_ar: BoolProperty(
        name="Export USDZ for AR",
        description="Also export product.usdz (iOS AR Quick Look) alongside the "
                    "GLB (Android Scene Viewer) — Sketchfab-style View in AR",
        default=True)
    # --- Shopify variant ---
    product_price: StringProperty(name="Price", default="49.00",
                                  description="Shopify/buy-panel price (variant currency below)")
    product_currency: StringProperty(name="Currency", default="USD")
    product_sku: StringProperty(name="SKU", default="")
    product_vendor: StringProperty(name="Vendor / Brand", default="")
    product_object: StringProperty(
        name="Product Object",
        description="Mesh to create LODs from and showcase (blank = active mesh)")
    # --- LODs: three versions, visitor picks quality on the site ---
    lod_high_ratio: FloatProperty(
        name="High Ratio", default=1.0, min=0.3, max=1.0,
        description="High LOD keeps this fraction of faces (1.0 = original "
                    "detail, cleanup only — no heavy optimization)")
    lod_medium_ratio: FloatProperty(
        name="Medium Ratio", default=0.45, min=0.05, max=1.0,
        description="Medium LOD keeps this fraction of faces")
    lod_low_ratio: FloatProperty(
        name="Low Ratio", default=0.12, min=0.02, max=1.0,
        description="Low LOD keeps this fraction of faces (fast on mobile)")
    default_quality: EnumProperty(
        name="Site Default Quality",
        description="Which LOD the showcase loads first. The visitor can "
                    "switch Low / Medium / High on the site at any time",
        items=[
            ("AUTO", "Auto (device)", "Low on mobile / data-saver, High on desktop"),
            ("LOW", "Low", "Always start on the Low LOD"),
            ("MEDIUM", "Medium", "Always start on the Medium LOD"),
            ("HIGH", "High", "Always start on the High LOD"),
        ],
        default="AUTO")
    lod_high_object: StringProperty(name="High LOD Object", default="")
    lod_medium_object: StringProperty(name="Medium LOD Object", default="")
    lod_low_object: StringProperty(name="Low LOD Object", default="")
    lod_faces_high: bpy.props.IntProperty(name="High LOD Faces", default=0)
    lod_faces_medium: bpy.props.IntProperty(name="Medium LOD Faces", default=0)
    lod_faces_low: bpy.props.IntProperty(name="Low LOD Faces", default=0)
    # --- Legacy single-copy optimize (kept for agent-tool compat) ---
    optimize_strategy: EnumProperty(
        name="Optimize Strategy",
        description="How the web copy is reduced. Decimate is fastest but "
                    "destroys topology/UVs; QuadriFlow/Voxel retopologise, "
                    "Limited Dissolve cleans planar CAD, Smart picks per-mesh",
        items=[
            ("SMART", "Smart (auto-pick)", "Analyse mesh and pick Decimate / QuadriFlow / Limited Dissolve automatically; bakes detail back when enabled"),
            ("DECIMATE", "Decimate (Collapse)", "Classic Decimate collapse — fast, good for organic/high-poly, destroys edge flow"),
            ("QUADRIFLOW", "QuadriFlow Retopo", "Clean quad retopology — best for deforming/hero products, preserves silhouette"),
            ("VOXEL", "Voxel Remesh", "Uniform voxel remesh — best for sculpt/photogrammetry cleanup before QuadriFlow"),
            ("LIMITED_DISSOLVE", "Limited Dissolve", "Dissolve near-planar faces — best for hard-surface / CAD, near-lossless"),
        ],
        default="SMART")
    target_ratio: FloatProperty(
        name="Decimate Ratio", default=0.35, min=0.02, max=1.0,
        description="Keep this fraction of faces (Decimate / Smart fallback)")
    quadriflow_faces: bpy.props.IntProperty(
        name="QuadriFlow Target Faces", default=8000, min=500, max=200000,
        description="Target face count for QuadriFlow retopology")
    voxel_size: FloatProperty(
        name="Voxel Size", default=0.02, min=0.001, max=0.5,
        description="Voxel remesh cell size (smaller = more detail, more faces)")
    preserve_sharp: BoolProperty(
        name="Preserve Sharp Edges", default=True,
        description="QuadriFlow: keep sharp edges / material boundaries")
    clean_first: BoolProperty(name="Clean Mesh First", default=True)
    faces_before: bpy.props.IntProperty(name="Faces Before", default=0)
    faces_after: bpy.props.IntProperty(name="Faces After", default=0)
    optimized_object: StringProperty(name="Optimized Object", default="")
    # --- Bake: capture high-poly detail onto the low-poly web copy ---
    bake_enabled: BoolProperty(
        name="Bake Detail Before Export",
        description="Bake Normal + AO (and optionally Roughness) from the "
                    "original high-poly mesh onto the optimized copy, then "
                    "wire the maps into its material before the GLB export. "
                    "This is why you don't need to keep all the polygons",
        default=True)
    bake_resolution: EnumProperty(
        name="Bake Resolution",
        items=[("512", "512", ""), ("1024", "1024", ""), ("2048", "2048", ""), ("4096", "4096", "")],
        default="1024")
    bake_normal: BoolProperty(name="Bake Normal Map", default=True)
    bake_ao: BoolProperty(name="Bake Ambient Occlusion", default=True)
    bake_margin: bpy.props.IntProperty(
        name="Bake Margin (px)", default=16, min=0, max=64,
        description="Padding beyond UV islands to hide seams")
    bake_cage_extrusion: FloatProperty(
        name="Cage Extrusion", default=0.02, min=0.0, max=0.5,
        description="Ray distance for Selected-to-Active baking")
    bake_status: StringProperty(name="Bake Status", default="")
    # --- Animation: scroll-scrubbed variants baked into the GLB ---
    animation_style: EnumProperty(
        name="Animation",
        items=[
            ("TURNTABLE", "Turntable 360°", "One even 360° spin (Linear) — the classic product turntable"),
            ("TURNTABLE_FLOAT", "Turntable + Float", "Turntable plus a gentle sine bob"),
            ("HERO_REVEAL", "Hero Reveal", "Scale-up + half-spin with Back ease — dramatic entrance, settles at hero pose"),
            ("ORBIT_REVEAL", "Orbit Reveal", "Eased orbit (270°) + rise + scale reveal — cinematic scroll story"),
            ("FLOAT_SPIN", "Float Spin (loop)", "Slow continuous spin + floating sine — idle loop at top of page"),
            ("PULSE", "Pulse Showcase", "Spin + rhythmic scale pulse — draws the eye to form"),
            ("SWING", "Swing / Pendulum", "Hanging-product pendulum swing on X/Z — playful, toy-like"),
            ("TILT_ORBIT", "Tilt Orbit", "Tilted turntable (12° X) — shows top + side in one pass"),
            ("DIORAMA_ORBIT", "Diorama Orbit", "Locked isometric tilt (35.264°) + slow orbit + bob — miniature diorama presentation"),
            ("EXPLODE_FLOAT", "Explode Float", "Float + subtle scale breathing (single-mesh explode proxy) — tech-product feel"),
            ("DROP_BOUNCE", "Drop Bounce (entrance)", "Sketchfab animated entrance: drops in with a bounce settle — autostart hero"),
            ("TUMBLE_360", "Tumble 360°", "Full X tumble + half Z spin — shows top, bottom and every side in one loop"),
            ("ELEVATE_REVEAL", "Elevate Reveal", "Rises from below with spin + Back-ease scale settle — cinematic product entrance"),
            ("NONE", "None (keep existing)", "Do not add animation"),
        ],
        default="TURNTABLE")
    animation_frames: bpy.props.IntProperty(
        name="Animation Frames", default=120, min=12, max=960)
    brand_name: StringProperty(name="Brand / Product Name", default="")
    accent_color: FloatVectorProperty(
        name="Accent Colour", subtype="COLOR", size=3, min=0.0, max=1.0,
        default=(0.91, 0.36, 0.16))
    dark_background: BoolProperty(name="Dark Site Background", default=True)
    scroll_scrub: BoolProperty(
        name="Scroll Scrubs Animation",
        description="GSAP ScrollTrigger scrubs the Blender animation while scrolling",
        default=True)
    # --- Three.js lighting / presentation (baked into site config) ---
    lighting_preset: EnumProperty(
        name="Lighting Preset",
        description="Three.js IBL + 3-point rig preset written into the site",
        items=[
            ("STUDIO", "Studio (IBL + 3-point)", "RoomEnvironment IBL, warm key / cool fill / rim, soft shadows — product hero"),
            ("STUDIO_SOFT", "Studio Soft", "Higher IBL, lower contrast, larger shadow radius — cosmetics / matte products"),
            ("SUNSET", "Sunset / Golden", "Warm key, teal fill, strong rim — lifestyle / outdoor products"),
            ("DRAMATIC", "Dramatic / Noir", "Single hard key, minimal fill, deep shadows — premium / jewellery"),
            ("DIORAMA", "Diorama (miniature)", "Locked isometric camera, toy-scale lighting, contact shadow — miniature world"),
        ],
        default="STUDIO")
    env_intensity: FloatProperty(
        name="Environment Intensity", default=0.9, min=0.0, max=2.5,
        description="IBL intensity (scene.environmentIntensity, r163+ with fallback)")
    exposure: FloatProperty(
        name="Exposure", default=1.1, min=0.4, max=2.0,
        description="ACES Filmic tone-mapping exposure")
    diorama_mode: BoolProperty(
        name="Diorama Mode",
        description="Lock the site camera to a 35.264° isometric diorama view, "
                    "disable pan/zoom drift, and add a miniature base plinth",
        default=False)
    auto_rotate_idle: BoolProperty(
        name="Idle Auto-Rotate",
        description="Slowly rotate the product when the visitor is at the top / idle",
        default=True)
    # --- Build harness / local server ---
    site_port: bpy.props.IntProperty(
        name="Site Port", default=8000, min=1024, max=65535,
        description="Preferred port for the local showcase server (harness finds the next free port if busy)")
    build_validate: BoolProperty(
        name="Validate After Build", default=True,
        description="Harness checks GLB, content.json and index.html after every build")
    export_dir: StringProperty(
        name="Website Folder",
        description="Where index.html + product.glb are written (blank = muse_website next to the .blend)",
        default="", subtype="DIR_PATH")
    status: StringProperty(
        name="Showcase Status",
        default="0) Improve Prompt. 1) Create LODs. 2) Animation. 3) CMS. 4) Build Website (catalogue + 360 renders included).")
    last_site_dir: StringProperty(name="Last Website Folder", default="")
    language_index: bpy.props.IntProperty(name="Language Index", default=0)
    entry_index: bpy.props.IntProperty(name="Entry Index", default=0)
    new_language_code: StringProperty(name="New Language Code", default="es")
    new_language_label: StringProperty(name="New Language Label", default="Español")
    new_entry_key: StringProperty(name="New Entry Key", default="custom_title")
    new_entry_section: StringProperty(name="New Entry Section", default="Custom")


classes = (MuseHistoryItem, MuseSceneSettings, MuseObjectSettings,
           MuseChatMessage, MuseAgentSettings, MuseCloudSettings,
           MuseSplatSettings,
           MuseSiteTranslation, MuseSiteLanguage, MuseSiteEntry, MuseSiteSettings)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.muse = PointerProperty(type=MuseSceneSettings)
    bpy.types.Scene.muse_history = CollectionProperty(type=MuseHistoryItem)
    bpy.types.Object.muse = PointerProperty(type=MuseObjectSettings)
    bpy.types.Scene.muse_agent = PointerProperty(type=MuseAgentSettings)
    bpy.types.Scene.muse_chat = CollectionProperty(type=MuseChatMessage)
    bpy.types.Scene.muse_cloud = PointerProperty(type=MuseCloudSettings)
    bpy.types.Scene.muse_site = PointerProperty(type=MuseSiteSettings)
    bpy.types.Scene.muse_site_languages = CollectionProperty(type=MuseSiteLanguage)
    bpy.types.Scene.muse_site_entries = CollectionProperty(type=MuseSiteEntry)
    bpy.types.Scene.muse_splat = PointerProperty(type=MuseSplatSettings)


def unregister():
    del bpy.types.Scene.muse
    del bpy.types.Scene.muse_history
    del bpy.types.Object.muse
    del bpy.types.Scene.muse_agent
    del bpy.types.Scene.muse_chat
    del bpy.types.Scene.muse_cloud
    del bpy.types.Scene.muse_site
    del bpy.types.Scene.muse_site_languages
    del bpy.types.Scene.muse_site_entries
    del bpy.types.Scene.muse_splat
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
