"""Static Three.js product-showcase template (generated per export).

The generated site is a plain folder — index.html + product.glb — with the
Blender CMS baked in as embedded JSON (so it opens from file:// too) plus a
content.json copy. Three.js (pinned) renders the GLB; GSAP ScrollTrigger
scrubs the Blender-baked animation and camera move while the visitor
scrolls through the CMS sections. The language switcher swaps every
[data-i18n] string from the embedded locales (default-language fallback was
already applied in Blender by web_cms.build_locales).

Lighting follows the `threejs-lighting` + `threejs-visual` skills:
IBL via PMREM RoomEnvironment is mandatory (never a lone DirectionalLight),
a subject-aware 3-point rig (warm key / cool fill / rim) with one shadow-
casting light, PCFSoft shadows with a tight frustum + normalBias, ACES
Filmic tone mapping, and `scene.environmentIntensity` (r163+) with a
per-material `envMapIntensity` fallback for older three builds. Presets
(STUDIO / STUDIO_SOFT / SUNSET / DRAMATIC / DIORAMA) are baked from
Blender into `DATA.config` and picked at runtime — no rebuild needed to
retune the CMS, only to change the preset.
"""

SITE_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title data-i18n="brand">Product</title>
<style>
  :root{ --accent:__ACCENT__; --bg:__BG__; --fg:__FG__; --muted:__MUTED__; --card:__CARD__; }
  *{box-sizing:border-box} html{scroll-behavior:smooth}
  body{margin:0;background:var(--bg);color:var(--fg);
       font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif;overflow-x:hidden}
  #stage{position:fixed;inset:0;z-index:0}
  #stage canvas{display:block;width:100%;height:100%;touch-action:pan-y}
  header{position:fixed;inset:0 0 auto 0;z-index:5;display:flex;justify-content:space-between;
         align-items:center;gap:12px;padding:16px 22px;pointer-events:none}
  header>*{pointer-events:auto}
  .brand{font-weight:800;letter-spacing:.02em;font-size:18px}
  .brand b{color:var(--accent)}
  nav{display:flex;gap:16px;font-size:14px}
  nav a{color:var(--muted);text-decoration:none} nav a:hover{color:var(--fg)}
  #langs{display:flex;gap:6px;flex-wrap:wrap}
  .lang{border:1px solid color-mix(in srgb,var(--fg) 25%, transparent);background:transparent;
        color:var(--muted);border-radius:999px;padding:6px 12px;cursor:pointer;font-size:13px}
  .lang.active{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:700}
  #quality{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
  #quality .qlabel{color:var(--muted);font-size:12.5px}
  main{position:relative;z-index:2}
  section{min-height:100vh;display:flex;align-items:center;padding:110px 6vw;pointer-events:none}
  .card{max-width:560px;pointer-events:none;background:var(--card);border:1px solid
        color-mix(in srgb,var(--fg) 10%, transparent);border-radius:8px;padding:34px 36px;
        backdrop-filter:blur(10px)}
  section:nth-child(even){justify-content:flex-end}
  .kicker{color:var(--accent);font-weight:700;font-size:13px;letter-spacing:.08em;text-transform:uppercase}
  h1{font-size:clamp(40px,7vw,76px);line-height:.98;margin:14px 0 16px}
  h2{font-size:clamp(30px,4.5vw,48px);line-height:1.05;margin:10px 0 14px}
  p{color:var(--muted);font-size:17px;line-height:1.65;margin:0 0 14px}
  .cta{display:inline-block;margin-top:8px;background:var(--accent);color:#fff;font-weight:700;
       padding:13px 24px;border-radius:999px;text-decoration:none}
  .grid{display:grid;gap:14px}
  .feat{background:var(--card);border:1px solid color-mix(in srgb,var(--fg) 10%, transparent);
        border-radius:8px;padding:22px;pointer-events:none;backdrop-filter:blur(10px)}
  .card a, .feat a{pointer-events:auto}
  .feat h3{margin:0 0 8px;font-size:19px} .feat p{font-size:15px;margin:0}
  #stats{font-variant-numeric:tabular-nums;color:var(--fg)}
  #loader{position:fixed;inset:0;z-index:9;display:grid;place-items:center;background:var(--bg);
          transition:opacity .5s;font-size:14px;color:var(--muted)}
  #err{position:fixed;left:12px;right:12px;bottom:12px;z-index:10;display:none;background:#5b1d1d;
       color:#ffd7d7;padding:12px 16px;border-radius:12px;font-size:14px;white-space:pre-wrap}
  #hint{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);z-index:4;color:var(--muted);
        font-size:12.5px;background:var(--card);padding:7px 14px;border-radius:999px;pointer-events:none;
        backdrop-filter:blur(8px)}
  #badge{position:fixed;right:14px;bottom:14px;z-index:4;color:var(--muted);font-size:11.5px;
         background:var(--card);border:1px solid color-mix(in srgb,var(--fg) 10%, transparent);
         padding:6px 10px;border-radius:999px;pointer-events:none;backdrop-filter:blur(8px)}
  @media (max-width:640px){ nav{display:none} .card{padding:26px 22px} section{padding:96px 18px} #badge{display:none} }
</style>
</head>
<body>
<div id="stage" aria-label="3D product view"></div>
<header>
  <div class="brand"><b>◆</b> <span data-i18n="brand">Product</span></div>
  <nav>
    <a href="#story" data-i18n="nav_story">Story</a>
    <a href="#features" data-i18n="nav_features">Features</a>
    <a href="#specs" data-i18n="nav_specs">Specs</a>
  </nav>
  <div id="langs" role="group" aria-label="Language"></div>
  <div id="quality" role="group" aria-label="Quality">
    <span class="qlabel">Quality</span>
    <button class="lang qbtn" data-q="low">Low</button>
    <button class="lang qbtn" data-q="medium">Medium</button>
    <button class="lang qbtn" data-q="high">High</button>
  </div>
</header>
<main>
  <section id="hero">
    <div class="card reveal">
      <div class="kicker" data-i18n="hero_kicker"></div>
      <h1 data-i18n="hero_title"></h1>
      <p data-i18n="hero_subtitle"></p>
      <a class="cta" href="#story" data-i18n="hero_cta"></a>
    </div>
  </section>
  <section id="story">
    <div class="card reveal">
      <h2 data-i18n="story_title"></h2>
      <p data-i18n="story_body"></p>
    </div>
  </section>
  <section id="features">
    <div class="grid">
      <div class="feat reveal"><h3 data-i18n="feature_1_title"></h3><p data-i18n="feature_1_body"></p></div>
      <div class="feat reveal"><h3 data-i18n="feature_2_title"></h3><p data-i18n="feature_2_body"></p></div>
      <div class="feat reveal"><h3 data-i18n="feature_3_title"></h3><p data-i18n="feature_3_body"></p></div>
    </div>
  </section>
  <section id="specs">
    <div class="card reveal">
      <h2 data-i18n="specs_title"></h2>
      <p data-i18n="specs_body"></p>
      <p id="stats"></p>
    </div>
  </section>
  <section id="buy">
    <div class="card reveal">
      <h2 data-i18n="cta_title"></h2>
      <p data-i18n="cta_body"></p>
      <a class="cta" href="#hero" data-i18n="cta_button"></a>
    </div>
  </section>
</main>
<footer style="position:relative;z-index:2;text-align:center;padding:26px 26px 76px;color:var(--muted);font-size:13px">
  <span data-i18n="footer_text"></span>
</footer>
<div id="hint">Drag to orbit · Scroll to explore</div>
<div id="badge"></div>
<div id="loader">Loading product…</div>
<div id="err" role="alert"></div>

<script id="site-data" type="application/json">__SITE_DATA__</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/ScrollTrigger.min.js"></script>
<script type="importmap">
{"imports":{
  "three":"https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js",
  "three/addons/":"https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/"
}}
</script>
<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const DATA = JSON.parse(document.getElementById('site-data').textContent);
const CFG = DATA.config || {};
/* LOD quality: Low / Medium / High GLBs; visitor preference wins,
   then the Blender default, then Auto (low on mobile/data-saver). */
const LODS = (DATA.product && DATA.product.lods) || null;
function autoQuality(){
  const save = !!(navigator.connection && navigator.connection.saveData);
  const mobile = matchMedia('(pointer: coarse)').matches || innerWidth < 768;
  return (save || mobile) ? 'low' : 'high';
}
function resolveQuality(){
  const stored = localStorage.getItem('muse-site-quality');
  if (stored && (!LODS || LODS[stored])) return stored;
  const d = String(CFG.defaultQuality || (DATA.product && DATA.product.defaultQuality) || 'AUTO').toUpperCase();
  if (d === 'LOW' || d === 'MEDIUM' || d === 'HIGH'){
    const l = d.toLowerCase();
    if (!LODS || LODS[l]) return l;
  }
  const a = autoQuality();
  if (LODS && !LODS[a]) return LODS.medium ? 'medium' : Object.keys(LODS)[0];
  return a;
}
let currentQuality = resolveQuality();
const errBox = document.getElementById('err');
function showError(m){ errBox.style.display='block'; errBox.textContent = 'Error: ' + m; }
window.addEventListener('error', e => showError(e.message || 'script error'));

/* ---------- CMS / i18n ---------- */
const locales = DATA.locales || {}, fallback = DATA.defaultLanguage || 'en';
let lang = localStorage.getItem('muse-site-lang') || fallback;
if (!locales[lang]) lang = fallback;
const langsEl = document.getElementById('langs');
(DATA.languages || []).forEach(l => {
  const b = document.createElement('button');
  b.className = 'lang'; b.textContent = l.label || l.code; b.dataset.code = l.code;
  b.addEventListener('click', () => applyLanguage(l.code));
  langsEl.appendChild(b);
});
function applyLanguage(code){
  lang = locales[code] ? code : fallback;
  localStorage.setItem('muse-site-lang', lang);
  const dict = locales[lang] || {};
  document.documentElement.lang = lang;
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (dict[key]) el.textContent = dict[key];
  });
  document.querySelectorAll('.lang').forEach(b => b.classList.toggle('active', b.dataset.code === lang));
  updateStats();
}
function updateStats(){
  const p = DATA.product || {};
  const tier = (p.lods && p.lods[currentQuality]) || null;
  const faces = tier?.faces ?? p.facesAfter ?? p.facesBefore;
  const kb = tier?.glbKB ?? p.glbKB;
  document.getElementById('stats').textContent =
    `${p.name || 'Product'} · ${(faces ?? '—')} faces` +
    (p.facesBefore ? ` (original ${p.facesBefore})` : '') +
    (kb ? ` · ${kb} KB GLB` : '') +
    ` · quality: ${currentQuality}` +
    (p.animation ? ` · animation: ${p.animation}` : ' · no animation');
}
applyLanguage(lang);
document.getElementById('badge').textContent =
  `${CFG.lightingPreset || 'STUDIO'} · ${DATA.product?.animationStyle || 'turntable'}${CFG.dioramaMode ? ' · diorama' : ''}`;

/* ---------- Three.js stage: renderer (ACES + sRGB + PCFSoft shadows) ---------- */
const stage = document.getElementById('stage');
const renderer = new THREE.WebGLRenderer({ antialias:true, alpha:true, powerPreference:'high-performance' });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = CFG.exposure ?? 1.1;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
stage.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const DIORAMA = !!CFG.dioramaMode || CFG.lightingPreset === 'DIORAMA';
if (!DIORAMA) scene.background = null; // alpha page background shows through

/* ---------- IBL (mandatory): PMREM RoomEnvironment, never lights alone ----------
   RoomEnvironment gives PBR materials reflections + diffuse fill for free.
   `scene.environmentIntensity` is r163+; on older builds we fall back to
   traversing materials and setting envMapIntensity after the GLB loads. */
const pmrem = new THREE.PMREMGenerator(renderer);
const envTex = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
scene.environment = envTex;
const ENV_INTENSITY = CFG.envIntensity ?? 0.9;
if ('environmentIntensity' in scene) scene.environmentIntensity = ENV_INTENSITY;
if ('backgroundIntensity' in scene) scene.backgroundIntensity = 1.0;

/* ---------- Lighting presets: subject-aware 3-point rig ----------
   Ratios/colour temps follow the blender-lighting subject-class table
   (product 5:1:1.5 neutral, glass softer rim, etc.) translated to web:
   only the KEY casts shadows (1 shadow light = fast), fill/rim do not. */
const PRESETS = {
  STUDIO:       { hemi: 0.35, hemiSky: 0xffffff, hemiGround: 0x223044,
                  key: 2.6, keyColor: 0xfff2e0, keyPos: [4, 6, 3], shadowRadius: 4, shadowMap: 2048,
                  fill: 0.7, fillColor: 0xd6e6ff, fillPos: [-4, 2.5, 2.5],
                  rim: 1.5, rimColor: 0x9ec2ff, rimPos: [-2, 3.5, -4.5], exposure: CFG.exposure ?? 1.1, env: ENV_INTENSITY },
  STUDIO_SOFT:  { hemi: 0.55, hemiSky: 0xffffff, hemiGround: 0x2a2f3a,
                  key: 1.7, keyColor: 0xfff6ec, keyPos: [3, 5, 4], shadowRadius: 8, shadowMap: 2048,
                  fill: 1.0, fillColor: 0xe8efff, fillPos: [-4, 3, 3],
                  rim: 0.8, rimColor: 0xcfe0ff, rimPos: [0, 4, -4], exposure: CFG.exposure ?? 1.05, env: Math.min(ENV_INTENSITY + 0.25, 2.0) },
  SUNSET:       { hemi: 0.28, hemiSky: 0xffd9a8, hemiGround: 0x1c2b3a,
                  key: 2.9, keyColor: 0xffb36b, keyPos: [5, 3.2, 2], shadowRadius: 3, shadowMap: 2048,
                  fill: 0.45, fillColor: 0x7fd4ff, fillPos: [-5, 2, 3],
                  rim: 2.0, rimColor: 0xff8a5c, rimPos: [-1, 4, -5], exposure: CFG.exposure ?? 1.15, env: ENV_INTENSITY * 0.8 },
  DRAMATIC:     { hemi: 0.12, hemiSky: 0xffffff, hemiGround: 0x0a0d14,
                  key: 3.4, keyColor: 0xfff1dd, keyPos: [2.5, 6, 1.5], shadowRadius: 2, shadowMap: 2048,
                  fill: 0.18, fillColor: 0xbfd4ff, fillPos: [-4, 2, 3],
                  rim: 1.9, rimColor: 0xaac8ff, rimPos: [0, 5, -4.5], exposure: CFG.exposure ?? 1.0, env: ENV_INTENSITY * 0.55 },
  DIORAMA:      { hemi: 0.5, hemiSky: 0xffffff, hemiGround: 0x334155,
                  key: 2.2, keyColor: 0xfff3e2, keyPos: [4, 7, 3], shadowRadius: 6, shadowMap: 2048,
                  fill: 0.8, fillColor: 0xdceeff, fillPos: [-4, 4, 2],
                  rim: 1.0, rimColor: 0xbdd8ff, rimPos: [0, 5, -4], exposure: CFG.exposure ?? 1.08, env: ENV_INTENSITY },
};
const P = PRESETS[CFG.lightingPreset] || PRESETS.STUDIO;
renderer.toneMappingExposure = P.exposure;
if ('environmentIntensity' in scene) scene.environmentIntensity = P.env;

const hemi = new THREE.HemisphereLight(P.hemiSky, P.hemiGround, P.hemi);
scene.add(hemi);

function shadowedDirectional(color, intensity, pos, mapSize, radius){
  const l = new THREE.DirectionalLight(color, intensity);
  l.position.set(...pos);
  l.castShadow = true;
  l.shadow.mapSize.set(mapSize, mapSize);
  // Tight frustum around the product (product is normalised to ~2.3 units).
  l.shadow.camera.near = 0.5; l.shadow.camera.far = 25;
  l.shadow.camera.left = -4; l.shadow.camera.right = 4;
  l.shadow.camera.top = 4; l.shadow.camera.bottom = -4;
  l.shadow.bias = -0.0001;       // depth bias — fixes shadow acne
  l.shadow.normalBias = 0.02;    // bias along normal — fixes peter-panning/acne on curves
  l.shadow.radius = radius;      // PCFSoft blur radius
  scene.add(l); scene.add(l.target);
  return l;
}
const keyLight = shadowedDirectional(P.keyColor, P.key, P.keyPos, P.shadowMap, P.shadowRadius);
const fillLight = new THREE.DirectionalLight(P.fillColor, P.fill);
fillLight.position.set(...P.fillPos); scene.add(fillLight); scene.add(fillLight.target);
const rimLight = new THREE.DirectionalLight(P.rimColor, P.rim);
rimLight.position.set(...P.rimPos); scene.add(rimLight); scene.add(rimLight.target);

/* Ground: catches the key shadow (ShadowMaterial) over a soft disc.
   In diorama mode a low plinth (cylinder) grounds the miniature. */
const GROUND_Y = -1.12;
const shadowCatcher = new THREE.Mesh(
  new THREE.CircleGeometry(3.1, 64),
  new THREE.ShadowMaterial({ opacity: DIORAMA ? 0.32 : 0.28 }));
shadowCatcher.rotation.x = -Math.PI/2; shadowCatcher.position.y = GROUND_Y;
shadowCatcher.receiveShadow = true; scene.add(shadowCatcher);
const disc = new THREE.Mesh(
  new THREE.CircleGeometry(2.6, 64),
  new THREE.MeshStandardMaterial({ color: DIORAMA ? 0x141c29 : 0x11151d, roughness: 0.95, metalness: 0 }));
disc.rotation.x = -Math.PI/2; disc.position.y = GROUND_Y - 0.001; disc.receiveShadow = true; scene.add(disc);
let plinth = null;
if (DIORAMA){
  plinth = new THREE.Mesh(
    new THREE.CylinderGeometry(1.55, 1.7, 0.22, 64),
    new THREE.MeshStandardMaterial({ color: 0x232f42, roughness: 0.7, metalness: 0.05 }));
  plinth.position.y = GROUND_Y + 0.11; plinth.receiveShadow = true; plinth.castShadow = false;
  scene.add(plinth);
}

/* ---------- Camera + controls (diorama locks to isometric) ---------- */
const ISO = THREE.MathUtils.degToRad(35.264); // isometric elevation
const camera = new THREE.PerspectiveCamera(DIORAMA ? 36 : 42, innerWidth/innerHeight, 0.1, 100);
if (DIORAMA){
  camera.position.set(4.6, 4.6 * Math.tan(ISO) + 1.4, 4.6);
} else {
  camera.position.set(3.4, 1.9, 5.2);
}
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true; controls.dampingFactor = 0.06;
controls.target.set(0, DIORAMA ? -0.25 : 0, 0);
if (DIORAMA){
  // Locked miniature: gentle orbit only, no flip, no zoom drift.
  controls.enablePan = false; controls.enableZoom = false;
  controls.minPolarAngle = ISO - 0.12; controls.maxPolarAngle = ISO + 0.12;
  controls.minAzimuthAngle = -0.9; controls.maxAzimuthAngle = 0.9;
  controls.autoRotate = false;
  document.getElementById('hint').textContent = 'Drag to look around the diorama · Scroll to explore';
} else {
  controls.enablePan = false; controls.enableZoom = false;
  controls.minPolarAngle = 0.35; controls.maxPolarAngle = Math.PI * 0.62;
}

const productGroup = new THREE.Group(); scene.add(productGroup);
let mixer = null, action = null, clipDuration = 0, currentModel = null;
const PIXEL_RATIO = { low: 1, medium: Math.min(devicePixelRatio, 1.5), high: Math.min(devicePixelRatio, 2) };
const gltfLoader = new GLTFLoader();
function disposeModel(root){
  root.traverse(o => {
    if (o.isMesh){
      if (o.geometry) o.geometry.dispose();
      const mats = Array.isArray(o.material) ? o.material : (o.material ? [o.material] : []);
      mats.forEach(m => { for (const k in m){ const v = m[k]; if (v && v.isTexture) v.dispose(); } m.dispose(); });
    }
  });
}
function loadQuality(level){
  const tier = LODS && LODS[level];
  const url = tier ? tier.model : (DATA.product.model || 'product.glb');
  const prevFraction = (action && clipDuration) ? (action.time % clipDuration) / clipDuration : 0;
  gltfLoader.load(url, gltf => {
    const model = gltf.scene;
    // Shadow flags + env fallback (older three without environmentIntensity).
    model.traverse(o => {
      if (o.isMesh){ o.castShadow = true; o.receiveShadow = false; }
      if (o.isMesh && o.material && !('environmentIntensity' in scene)){
        const mats = Array.isArray(o.material) ? o.material : [o.material];
        mats.forEach(m => { if ('envMapIntensity' in m) m.envMapIntensity = P.env; });
      }
    });
    const box3 = new THREE.Box3().setFromObject(model);
    const size = box3.getSize(new THREE.Vector3());
    const centre = box3.getCenter(new THREE.Vector3());
    const scale = 2.3 / Math.max(size.x, size.y, size.z, 0.0001);
    model.scale.setScalar(scale);
    model.position.sub(centre.multiplyScalar(scale));
    if (DIORAMA) model.position.y += 0.22; // sit on the plinth
    if (currentModel){ productGroup.remove(currentModel); disposeModel(currentModel); }
    if (mixer){ mixer.stopAllAction(); mixer = null; action = null; clipDuration = 0; }
    currentModel = model;
    productGroup.add(model);
    if (gltf.animations && gltf.animations.length){
      mixer = new THREE.AnimationMixer(model);
      action = mixer.clipAction(gltf.animations[0]);
      clipDuration = gltf.animations[0].duration || 0;
      action.play(); action.paused = true;
      if (prevFraction) action.time = prevFraction * clipDuration;
    }
    currentQuality = level;
    localStorage.setItem('muse-site-quality', level);
    renderer.setPixelRatio(PIXEL_RATIO[level] || Math.min(devicePixelRatio, 2));
    document.querySelectorAll('.qbtn').forEach(b => b.classList.toggle('active', b.dataset.q === level));
    document.getElementById('badge').textContent =
      `${CFG.lightingPreset || 'STUDIO'} · ${DATA.product?.animationStyle || 'turntable'} · ${level}${CFG.dioramaMode ? ' · diorama' : ''}`;
    updateStats();
    const loaderEl = document.getElementById('loader');
    if (loaderEl){ loaderEl.style.opacity = '0'; setTimeout(() => loaderEl.remove(), 550); }
  }, undefined, e => { showError('Could not load the product model: ' + (e.message || e)); });
}
document.querySelectorAll('.qbtn').forEach(b =>
  b.addEventListener('click', () => { if (b.dataset.q !== currentQuality) loadQuality(b.dataset.q); }));
if (!LODS) document.getElementById('quality').style.display = 'none';
loadQuality(currentQuality);

/* ---------- GSAP scroll choreography ---------- */
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const scrollState = { progress: 0 };
if (window.gsap && window.ScrollTrigger){
  gsap.registerPlugin(ScrollTrigger);
  ScrollTrigger.create({
    trigger: document.body, start: 'top top', end: 'bottom bottom', scrub: 0.6,
    onUpdate: self => { scrollState.progress = self.progress; }
  });
  gsap.utils.toArray('.reveal').forEach(el => {
    gsap.from(el, { opacity: 0, y: reduced ? 0 : 18, duration: reduced ? 0 : 0.6,
      scrollTrigger: { trigger: el, start: 'top 82%' } });
  });
}
const AUTO_IDLE = CFG.autoRotateIdle !== false;
const clock = new THREE.Clock();
function tick(){
  requestAnimationFrame(tick);
  const t = clock.getElapsedTime();
  const p = scrollState.progress;
  const scrubbing = DATA.config && DATA.config.scrollScrub !== false && !reduced;
  if (action && mixer && scrubbing){
    if (p > 0.005){
      action.time = p * clipDuration;       // Blender animation, scrubbed by scroll
    } else {
      action.time = (t * 0.6) % (clipDuration || 1);  // idle: play it at the top
    }
    mixer.update(0);
  } else if (!reduced && !DIORAMA){
    // No GLB animation: turntable fallback, idle spin only at the top.
    productGroup.rotation.y = p * Math.PI * 2 + (p < 0.02 && AUTO_IDLE ? t * 0.25 : 0);
  } else if (!reduced && DIORAMA && AUTO_IDLE && p < 0.02){
    productGroup.rotation.y = Math.sin(t * 0.18) * 0.06; // barely-there diorama sway
  }
  if (!DIORAMA){
    const fov = 42 - p * 7;                   // scroll dolly that never fights OrbitControls
    if (Math.abs(camera.fov - fov) > 0.01){ camera.fov = fov; camera.updateProjectionMatrix(); }
  }
  controls.update();
  renderer.render(scene, camera);
}
tick();
addEventListener('resize', () => {
  camera.aspect = innerWidth/innerHeight; camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});
</script>
</body>
</html>
"""


def render_site_html(site_data_json: str, accent_hex: str = "#e85c29",
                     dark: bool = True, variant: str = "SHOWCASE") -> str:
    bg = "#0d1017" if dark else "#f4f1ec"
    fg = "#f2f4f8" if dark else "#181a20"
    muted = "#a7b0bf" if dark else "#5a6070"
    card = "rgba(16,20,28,.72)" if dark else "rgba(255,255,255,.82)"

    def fill(template: str) -> str:
        return (template.replace("__SITE_DATA__", site_data_json)
                .replace("__ACCENT__", accent_hex)
                .replace("__BG__", bg).replace("__FG__", fg)
                .replace("__MUTED__", muted).replace("__CARD__", card))

    variant = (variant or "SHOWCASE").upper()
    if variant == "SHOPIFY":
        return fill(SHOPIFY_HTML)
    if variant == "CONFIGURATOR":
        return fill(CONFIGURATOR_HTML)
    return fill(SITE_HTML)


# ---------------------------------------------------------------------------
# Shared viewer JS for the store/configurator variants.
# Three.js per cloudai-x/threejs-skills (loaders/lighting/interaction):
# GLTFLoader + PMREM RoomEnvironment IBL (never lights alone), ACES +
# PCFSoft shadows, OrbitControls with damping. 360° per Scaleflex
# cloudimage-360-view v4 (data-folder / data-filename-x / data-amount-x).
# ---------------------------------------------------------------------------

_VIEWER_JS = r"""
const DATA = JSON.parse(document.getElementById('site-data').textContent);
const P = DATA.product || {}, CFG = DATA.config || {};
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
function money(v){ const n = parseFloat(v); return isNaN(n) ? (v||'') :
  new Intl.NumberFormat(undefined,{style:'currency',currency:P.currency||'USD'}).format(n); }
let spinViewer = null;
function initSpin(plan){
  const el = $('#spin360'); if (!el || !plan) return;
  el.innerHTML = '';
  const div = document.createElement('div');
  div.className = 'cloudimage-360';
  div.dataset.folder = plan.folder; div.dataset.filenameX = plan.filename;
  div.dataset.amountX = plan.amount; div.dataset.responsive = 'true';
  el.appendChild(div);
  try { spinViewer = new window.CI360(); }
  catch(e){ try { window.CI360.init(div, {folder:plan.folder, filenameX:plan.filename, amountX:plan.amount}); } catch(_){} }
}
function addViewerToolbar(stage, ctx){
  const bar = document.createElement('div'); bar.className = 'vtoolbar';
  const views = document.createElement('div'); views.className = 'vgroup';
  (P.cameraViews || []).forEach(v => {
    const b = document.createElement('button'); b.textContent = v.label;
    b.addEventListener('click', () => ctx.flyTo(v.azimuth, v.elevation));
    views.appendChild(b);
  });
  bar.appendChild(views);
  const modes = document.createElement('div'); modes.className = 'vgroup';
  (P.displayModes || []).forEach(m => {
    const b = document.createElement('button'); b.textContent = m.label;
    if (m.id === 'shaded') b.classList.add('active');
    b.addEventListener('click', () => {
      modes.querySelectorAll('button').forEach(x => x.classList.toggle('active', x === b));
      ctx.setMode(m.id);
    });
    modes.appendChild(b);
  });
  bar.appendChild(modes);
  const ex = document.createElement('label'); ex.className = 'vexplode';
  ex.innerHTML = 'Explode <input type="range" min="0" max="100" value="0">';
  ex.querySelector('input').addEventListener('input', e => ctx.setExplode(e.target.value/100));
  bar.appendChild(ex);
  const fs = document.createElement('button'); fs.textContent = 'Fullscreen';
  fs.addEventListener('click', () => { if (stage.requestFullscreen) stage.requestFullscreen(); });
  bar.appendChild(fs);
  const shot = document.createElement('button'); shot.textContent = 'Screenshot';
  shot.addEventListener('click', () => ctx.screenshot());
  bar.appendChild(shot);
  if (P.ar && P.ar.usdz){
    const ar = document.createElement('a'); ar.className = 'vbutton'; ar.textContent = 'View in AR';
    ar.href = P.ar.usdz; ar.setAttribute('rel', 'ar'); bar.appendChild(ar);
  }
  stage.appendChild(bar);
  const layer = document.createElement('div'); layer.className = 'hotspots';
  stage.appendChild(layer);
  const card = document.createElement('div'); card.className = 'hotcard'; card.hidden = true;
  stage.appendChild(card);
  return { layer, card };
}
async function init3D(){
  const stage = $('#stage3d'); if (!stage || stage.dataset.done) return;
  stage.dataset.done = '1';
  const THREE = await import('three');
  const { OrbitControls } = await import('three/addons/controls/OrbitControls.js');
  const { GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js');
  const { RoomEnvironment } = await import('three/addons/environments/RoomEnvironment.js');
  const renderer = new THREE.WebGLRenderer({antialias:true, alpha:true, preserveDrawingBuffer:true});
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setSize(stage.clientWidth, stage.clientHeight);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  stage.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  if ('environmentIntensity' in scene) scene.environmentIntensity = CFG.envIntensity ?? 0.9;
  const key = new THREE.DirectionalLight(0xfff2e0, 2.6);
  key.position.set(4,6,3); key.castShadow = true;
  key.shadow.mapSize.set(2048,2048); key.shadow.bias = -0.0001; key.shadow.normalBias = 0.02;
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xd6e6ff, 0.7); fill.position.set(-4,2.5,2.5); scene.add(fill);
  const rim = new THREE.DirectionalLight(0x9ec2ff, 1.5); rim.position.set(-2,3.5,-4.5); scene.add(rim);
  const ground = new THREE.Mesh(new THREE.CircleGeometry(3.1,64), new THREE.ShadowMaterial({opacity:0.28}));
  ground.rotation.x = -Math.PI/2; ground.position.y = -1.12; ground.receiveShadow = true; scene.add(ground);
  const camera = new THREE.PerspectiveCamera(42, stage.clientWidth/stage.clientHeight, 0.1, 100);
  camera.position.set(3.4, 1.9, 5.2);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.enablePan = false;
  addEventListener('resize', () => {
    camera.aspect = stage.clientWidth/Math.max(stage.clientHeight,1);
    camera.updateProjectionMatrix(); renderer.setSize(stage.clientWidth, stage.clientHeight);
  });
  new GLTFLoader().load(P.model || 'product.glb', gltf => {
    const model = gltf.scene;
    model.traverse(o => { if (o.isMesh) o.castShadow = true; });
    const box = new THREE.Box3().setFromObject(model), size = box.getSize(new THREE.Vector3());
    const centre = box.getCenter(new THREE.Vector3()), s = 2.3/Math.max(size.x,size.y,size.z,1e-4);
    model.scale.setScalar(s); model.position.sub(centre.multiplyScalar(s));
    const group = new THREE.Group(); group.add(model); scene.add(group);
    // GLB clips need a mixer updated every frame (threejs-animation);
    // without a clip, idle-turntable so the view is alive and drag reads.
    let mixer = null;
    if (gltf.animations && gltf.animations.length){
      mixer = new THREE.AnimationMixer(model);
      mixer.clipAction(gltf.animations[0]).play();
    }
    controls.autoRotate = !mixer; controls.autoRotateSpeed = 0.9;
    controls.addEventListener('start', () => { controls.autoRotate = false; });
    // --- Sketchfab-style setups: bookmarks, display modes, explode, hotspots ---
    const parts = [];
    model.traverse(o => { if (o.isMesh){
      const c = new THREE.Box3().setFromObject(o).getCenter(new THREE.Vector3());
      parts.push({ mesh:o, base:o.position.clone(), dir:c.clone() });
    }});
    let fly = null;
    const ctx = {
      flyTo(azDeg, elDeg){
        const az = THREE.MathUtils.degToRad(azDeg), el = THREE.MathUtils.degToRad(elDeg), d = 5.4;
        fly = { from: camera.position.clone(), t: 0,
          to: new THREE.Vector3(d*Math.cos(el)*Math.sin(az), d*Math.sin(el)+0.4, d*Math.cos(el)*Math.cos(az)) };
        controls.autoRotate = false;
      },
      setMode(mode){
        // Product-only: never touch ground/lights (overrideMaterial would).
        if (!ctx._saved){ ctx._saved = [];
          model.traverse(o => { if (o.isMesh) ctx._saved.push([o, o.material]); }); }
        const clay = new THREE.MeshStandardMaterial({ color: 0xb8b0a4, roughness: 0.9, metalness: 0 });
        ctx._saved.forEach(([mesh, original]) => {
          if (mode === 'clay'){ mesh.material = clay; return; }
          mesh.material = original;
          const mats = Array.isArray(original) ? original : [original];
          mats.forEach(m => { if (!m) return; m.wireframe = mode==='wireframe';
            if ('transparent' in m){ m.transparent = mode==='xray'; m.opacity = mode==='xray' ? 0.35 : 1; }
            m.needsUpdate = true; });
        });
      },
      setExplode(f){
        parts.forEach(p => { p.mesh.position.copy(p.base).addScaledVector(p.dir, f * 0.55); });
      },
      screenshot(){
        renderer.render(scene, camera);
        const a = document.createElement('a');
        a.href = renderer.domElement.toDataURL('image/png');
        a.download = (P.name || 'product') + '.png'; a.click();
      },
    };
    const ui = addViewerToolbar(stage, ctx);
    const markers = (P.hotspots || []).map((h, i) => {
      const b = document.createElement('button'); b.className = 'hotspot';
      b.textContent = String(i + 1); b.setAttribute('aria-label', h.title);
      b.addEventListener('click', () => {
        ui.card.hidden = false;
        ui.card.innerHTML = '<strong></strong><p></p>';
        ui.card.querySelector('strong').textContent = h.title;
        ui.card.querySelector('p').textContent = h.body || '';
        ctx.flyTo(h.azimuth, h.elevation);
      });
      ui.layer.appendChild(b); return { h, el: b };
    });
    const clock = new THREE.Clock();
    (function tick(){ requestAnimationFrame(tick);
      const dt = Math.min(clock.getDelta(), 0.05);
      if (mixer) mixer.update(dt);
      if (fly){ fly.t = Math.min(1, fly.t + dt/0.7);
        const e = 1 - Math.pow(1 - fly.t, 3);
        camera.position.lerpVectors(fly.from, fly.to, e);
        if (fly.t >= 1) fly = null; }
      controls.update(); renderer.render(scene,camera);
      const w = stage.clientWidth, hh = stage.clientHeight;
      markers.forEach(({h, el}) => {
        const az = THREE.MathUtils.degToRad(h.azimuth), el2 = THREE.MathUtils.degToRad(h.elevation);
        const v = new THREE.Vector3(1.45*Math.cos(el2)*Math.sin(az), 1.45*Math.sin(el2), 1.45*Math.cos(el2)*Math.cos(az));
        const facing = v.clone().normalize().dot(camera.position.clone().normalize());
        const p = v.clone().project(camera);
        el.style.display = (facing > 0.05 && p.z < 1) ? 'block' : 'none';
        el.style.left = ((p.x*0.5+0.5)*w) + 'px'; el.style.top = ((-p.y*0.5+0.5)*hh) + 'px';
      });
    })();
  }, undefined, e => { stage.insertAdjacentHTML('beforeend','<p class="err">3D model failed to load.</p>'); });
}
"""

SHOPIFY_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title>Product — Store</title>
<style>
:root{--accent:__ACCENT__;--bg:__BG__;--fg:__FG__;--muted:__MUTED__;--card:__CARD__}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);font-family:Inter,system-ui,sans-serif}
header{display:flex;justify-content:space-between;align-items:center;padding:16px 24px;border-bottom:1px solid color-mix(in srgb,var(--fg) 12%, transparent)}
.brand{font-weight:800}.brand b{color:var(--accent)} button{font:inherit}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 60px}
.crumbs{color:var(--muted);font-size:13px;margin-bottom:18px}
.product{display:grid;grid-template-columns:1.15fr .85fr;gap:34px}
@media(max-width:820px){.product{grid-template-columns:1fr}}
.tabs{display:flex;gap:8px;margin-bottom:12px}
.tab{border:1px solid color-mix(in srgb,var(--fg) 20%, transparent);background:transparent;color:var(--muted);padding:8px 14px;border-radius:999px;cursor:pointer}
.tab.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.mainimg{width:100%;aspect-ratio:1;border-radius:12px;object-fit:cover;background:var(--card)}
#stage3d,#spin360{width:100%;aspect-ratio:1;border-radius:12px;overflow:hidden;background:var(--card)}
#stage3d canvas{width:100%;height:100%;display:block}
.thumbs{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.thumbs img{width:72px;height:72px;object-fit:cover;border-radius:8px;cursor:pointer;border:2px solid transparent}
.thumbs img.active{border-color:var(--accent)}
.price{font-size:30px;font-weight:800;margin:10px 0}
.buy{background:var(--accent);color:#fff;border:0;width:100%;padding:15px;border-radius:999px;font-weight:800;cursor:pointer}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:14px;margin-top:14px}
.grid figure{margin:0}.grid img{width:100%;aspect-ratio:1;object-fit:cover;border-radius:10px}
.grid figcaption{color:var(--muted);font-size:13px;margin-top:6px}
.err{color:#fda4a4}

#stage3d{position:relative}
.vtoolbar{position:absolute;left:10px;right:10px;bottom:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;z-index:3}
.vtoolbar button,.vtoolbar .vbutton{border:1px solid rgba(255,255,255,.25);background:rgba(10,12,18,.72);color:#eef1f6;padding:7px 11px;border-radius:6px;cursor:pointer;font-size:12.5px;text-decoration:none}
.vtoolbar button.active{background:var(--accent);border-color:var(--accent);color:#fff}
.vgroup{display:flex;gap:5px;flex-wrap:wrap}
.vexplode{display:flex;gap:6px;align-items:center;background:rgba(10,12,18,.72);padding:6px 10px;border-radius:6px;font-size:12.5px}
.hotspots{position:absolute;inset:0;pointer-events:none;z-index:2}
.hotspot{position:absolute;transform:translate(-50%,-50%);width:26px;height:26px;border-radius:50%;border:2px solid #fff;background:var(--accent);color:#fff;font-weight:800;cursor:pointer;pointer-events:auto}
.hotcard{position:absolute;top:10px;left:10px;max-width:280px;background:rgba(10,12,18,.85);padding:12px 14px;border-radius:8px;z-index:3}
.hotcard p{margin:6px 0 0;color:var(--muted);font-size:13.5px;line-height:1.5}
</style></head><body>
<header><div class="brand"><b>◆</b> <span id="storeName">Store</span></div>
<div>Cart (<span id="cartCount">0</span>)</div></header>
<div class="wrap">
<div class="crumbs">Home / Products / <span id="crumb"></span></div>
<div class="product">
<div>
  <div class="tabs">
    <button class="tab active" data-tab="photos">Photos</button>
    <button class="tab" data-tab="3d">3D</button>
    <button class="tab" data-tab="spin">360°</button>
  </div>
  <div id="pane-photos"><img class="mainimg" id="mainImg" alt=""><div class="thumbs" id="thumbs"></div></div>
  <div id="pane-3d" hidden><div id="stage3d" aria-label="Interactive 3D product view"></div>
  <p style="color:var(--muted)">Drag to orbit · Scroll to zoom</p></div>
  <div id="pane-spin" hidden><div id="spin360"></div><p style="color:var(--muted)">Drag to spin 360°</p></div>
</div>
<div>
  <div style="color:var(--muted)" id="vendor"></div>
  <h1 id="title" style="margin:8px 0"></h1>
  <div class="price" id="price"></div>
  <p id="desc" style="color:var(--muted);line-height:1.6"></p>
  <label>Quantity <input id="qty" type="number" value="1" min="1" style="width:70px"></label>
  <div style="height:14px"></div>
  <button class="buy" id="addCart">Add to cart</button>
  <p id="cartMsg" style="color:var(--muted)"></p>
  <p id="meta" style="color:var(--muted);font-size:14px"></p>
</div>
</div>
<h2 style="margin-top:44px">From every angle</h2>
<div class="grid" id="catalogue"></div>
</div>
<footer style="text-align:center;color:var(--muted);padding:24px">Rendered in Blender · Interactive 3D + 360° included</footer>
<script id="site-data" type="application/json">__SITE_DATA__</script>
<script src="https://cdn.cloudimage.io/360-view/4.10.0/360-view.min.js"></script>
<script type="importmap">{"imports":{"three":"https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js","three/addons/":"https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/"}}</script>
<script type="module">
__VIEWER_JS__
document.getElementById('title').textContent = P.name || 'Product';
document.getElementById('crumb').textContent = P.name || 'Product';
document.getElementById('storeName').textContent = (P.shopify && P.shopify.vendor) || P.name || 'Store';
document.getElementById('vendor').textContent = (P.shopify && P.shopify.vendor) || '';
document.getElementById('price').textContent = money(P.price);
document.getElementById('desc').textContent = (P.prompt && P.prompt.hero_subtitle) || P.description || '';
document.getElementById('meta').textContent =
  `${P.facesAfter ?? ''} faces · ${(P.lods&&Object.keys(P.lods).join('/'))||'3D'} · SKU ${((P.shopify||{}).variants||[{}])[0].sku || '—'}`;
const imgs = P.images || [];
const main = document.getElementById('mainImg'), thumbs = document.getElementById('thumbs');
function show(i){ if(!imgs[i]) return; main.src = imgs[i].file; main.alt = imgs[i].alt || '';
  [...thumbs.children].forEach((t,j)=>t.classList.toggle('active', i===j)); }
imgs.forEach((im,i)=>{ const t=document.createElement('img'); t.src=im.file; t.alt=im.alt||'';
  t.addEventListener('click',()=>show(i)); thumbs.appendChild(t); });
show(0);
const grid = document.getElementById('catalogue');
imgs.forEach(im=>{ const f=document.createElement('figure');
  f.innerHTML = `<img loading="lazy" src="${im.file}" alt="${im.alt||''}"><figcaption>${im.label||''}</figcaption>`;
  grid.appendChild(f); });
$$('.tab').forEach(b=>b.addEventListener('click',()=>{
  $$('.tab').forEach(x=>x.classList.toggle('active', x===b));
  ['photos','3d','spin'].forEach(k=>{ document.getElementById('pane-'+k).hidden = k!==b.dataset.tab; });
  if (b.dataset.tab==='3d') init3D();
  if (b.dataset.tab==='spin') initSpin(P.spin);
}));
let cart = 0;
document.getElementById('addCart').addEventListener('click',()=>{
  cart += parseInt(document.getElementById('qty').value||'1',10)||1;
  document.getElementById('cartCount').textContent = cart;
  document.getElementById('cartMsg').textContent = 'Added to cart (demo storefront — connect Shopify checkout to sell).';
});
</script></body></html>
"""

CONFIGURATOR_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title>Configure — Product</title>
<style>
:root{--accent:__ACCENT__;--bg:__BG__;--fg:__FG__;--muted:__MUTED__;--card:__CARD__}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);font-family:Inter,system-ui,sans-serif}
header{display:flex;justify-content:space-between;padding:16px 24px;border-bottom:1px solid color-mix(in srgb,var(--fg) 12%, transparent)}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 60px}
.layout{display:grid;grid-template-columns:1.2fr .8fr;gap:34px}
@media(max-width:820px){.layout{grid-template-columns:1fr}}
#spin360{width:100%;aspect-ratio:1;border-radius:12px;overflow:hidden;background:var(--card)}
#stage3d{width:100%;aspect-ratio:1;border-radius:12px;overflow:hidden;background:var(--card)}
#stage3d canvas{width:100%;height:100%;display:block}
.swatches{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}
.swatch{border:2px solid color-mix(in srgb,var(--fg) 20%, transparent);background:transparent;color:var(--fg);padding:10px 16px;border-radius:999px;cursor:pointer}
.swatch.active{border-color:var(--accent);background:var(--accent);color:#fff}
.buy{background:var(--accent);color:#fff;border:0;width:100%;padding:15px;border-radius:999px;font-weight:800;cursor:pointer}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}
.grid img{width:100%;aspect-ratio:1;object-fit:cover;border-radius:10px}
.price{font-size:28px;font-weight:800}

#stage3d{position:relative}
.vtoolbar{position:absolute;left:10px;right:10px;bottom:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;z-index:3}
.vtoolbar button,.vtoolbar .vbutton{border:1px solid rgba(255,255,255,.25);background:rgba(10,12,18,.72);color:#eef1f6;padding:7px 11px;border-radius:6px;cursor:pointer;font-size:12.5px;text-decoration:none}
.vtoolbar button.active{background:var(--accent);border-color:var(--accent);color:#fff}
.vgroup{display:flex;gap:5px;flex-wrap:wrap}
.vexplode{display:flex;gap:6px;align-items:center;background:rgba(10,12,18,.72);padding:6px 10px;border-radius:6px;font-size:12.5px}
.hotspots{position:absolute;inset:0;pointer-events:none;z-index:2}
.hotspot{position:absolute;transform:translate(-50%,-50%);width:26px;height:26px;border-radius:50%;border:2px solid #fff;background:var(--accent);color:#fff;font-weight:800;cursor:pointer;pointer-events:auto}
.hotcard{position:absolute;top:10px;left:10px;max-width:280px;background:rgba(10,12,18,.85);padding:12px 14px;border-radius:8px;z-index:3}
.hotcard p{margin:6px 0 0;color:var(--muted);font-size:13.5px;line-height:1.5}
</style></head><body>
<header><div><b style="color:var(--accent)">◆</b> Configurator</div><div id="finishName"></div></header>
<div class="wrap"><div class="layout">
<div>
  <div id="spin360" aria-label="360 degree product spin"></div>
  <p style="color:var(--muted)">Drag to spin · Double-click to zoom · Use ← → keys</p>
  <div id="stage3d" aria-label="Interactive 3D product view"></div>
  <p style="color:var(--muted)">Prefer true 3D? Drag to orbit the live model.</p>
</div>
<div>
  <h1 id="title"></h1><div class="price" id="price"></div>
  <p id="desc" style="color:var(--muted);line-height:1.6"></p>
  <h3>Finish</h3><div class="swatches" id="finishes"></div>
  <button class="buy" id="addCart">Add configured product to cart</button>
  <p id="cartMsg" style="color:var(--muted)"></p>
</div></div>
<h2 style="margin-top:40px">Catalogue</h2><div class="grid" id="catalogue"></div>
</div>
<script id="site-data" type="application/json">__SITE_DATA__</script>
<script src="https://cdn.cloudimage.io/360-view/4.10.0/360-view.min.js"></script>
<script type="importmap">{"imports":{"three":"https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js","three/addons/":"https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/"}}</script>
<script type="module">
__VIEWER_JS__
document.getElementById('title').textContent = P.name || 'Product';
document.getElementById('price').textContent = money(P.price);
document.getElementById('desc').textContent = (P.prompt && P.prompt.hero_subtitle) || P.description || '';
const spins = {}; (P.spins||[]).forEach(s=>{ spins[s.finish]=s; });
const box = document.getElementById('finishes');
(P.finishes||['Original']).forEach((f,i)=>{
  const b=document.createElement('button'); b.className='swatch'+(i===0?' active':''); b.textContent=f;
  b.addEventListener('click',()=>{ $$('.swatch').forEach(x=>x.classList.toggle('active',x===b));
    document.getElementById('finishName').textContent=f; initSpin(spins[f]||P.spin); });
  box.appendChild(b);
});
document.getElementById('finishName').textContent = (P.finishes||['Original'])[0];
initSpin(P.spin); init3D();
(P.images||[]).forEach(im=>{ const img=document.createElement('img');
  img.loading='lazy'; img.src=im.file; img.alt=im.alt||''; document.getElementById('catalogue').appendChild(img); });
document.getElementById('addCart').addEventListener('click',()=>{
  document.getElementById('cartMsg').textContent =
    `Added ${P.name||'product'} (${document.getElementById('finishName').textContent}) — demo configurator.`;
});
</script></body></html>
"""

# Inject the shared viewer JS into both variant templates.
SHOPIFY_HTML = SHOPIFY_HTML.replace("__VIEWER_JS__", _VIEWER_JS)
CONFIGURATOR_HTML = CONFIGURATOR_HTML.replace("__VIEWER_JS__", _VIEWER_JS)
