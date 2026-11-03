"""Build harness for the generated Three.js showcase site (bpy-free).

The harness is the boring-but-critical layer between "Blender exported
some files" and "a site a human can open": it validates the export,
finds a free port, probes whether a server is already serving the
folder, and writes a one-command serve script + manifest. Everything
here is pure Python so it can be unit-tested outside Blender.

Pipeline (called by showcase.build_website):
    validate_site(dir) -> [problems]     # empty list == healthy
    find_free_port(preferred) -> port    # preferred, else next free
    probe_site(port, dir) -> status dict # is something serving us?
    write_serve_script(dir, port)        # serve.py / README updated
    build_manifest(...) -> manifest.json # machine-readable build record
"""

from __future__ import annotations

import json
import os
import socket
import urllib.request
import urllib.error

DEFAULT_PORT = 8000
_PROBE_TIMEOUT = 0.6


def find_free_port(preferred: int = DEFAULT_PORT, span: int = 20) -> int:
    """Return `preferred` if bindable, else the next free port in span."""
    for port in range(int(preferred), int(preferred) + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    return int(preferred)


def is_port_listening(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(_PROBE_TIMEOUT)
        try:
            return sock.connect_ex((host, int(port))) == 0
        except OSError:
            return False


def probe_site(port: int, expect_dir: str = "") -> dict:
    """Probe http://127.0.0.1:<port>/ — is *our* showcase serving there?

    Returns {running, url, status, is_showcase, detail}. `is_showcase`
    is True only when the served HTML contains the embedded site-data
    marker, so a random other server on the port is not mistaken for us.
    """
    url = f"http://127.0.0.1:{int(port)}/"
    result = {"running": False, "url": url, "port": int(port),
              "status": None, "is_showcase": False, "detail": ""}
    if not is_port_listening(port):
        result["detail"] = "nothing listening on the port"
        return result
    result["running"] = True
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "muse-harness/1"})
        # Localhost must never go through a proxy (dev machines often have
        # http_proxy set with an empty no_proxy — that would 502 here).
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=2) as resp:  # noqa: S310 - localhost
            result["status"] = resp.status
            body = resp.read(65536).decode("utf-8", errors="ignore")
            result["is_showcase"] = ('id="site-data"' in body
                                     or "product.glb" in body
                                     or "Muse Product" in body)
            result["detail"] = "showcase HTML served" if result["is_showcase"] else "port serves other content"
    except urllib.error.HTTPError as exc:
        result["status"] = exc.code
        result["detail"] = f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - probe must never raise
        result["detail"] = f"{type(exc).__name__}: {exc}"
    return result


def validate_site(site_dir: str) -> list[str]:
    """Return a list of problems with the built site (empty == healthy)."""
    problems: list[str] = []
    index = os.path.join(site_dir, "index.html")
    glb = os.path.join(site_dir, "product.glb")
    content = os.path.join(site_dir, "content.json")
    if not os.path.isdir(site_dir):
        return [f"site folder missing: {site_dir}"]
    if not os.path.exists(index):
        problems.append("index.html missing")
    else:
        try:
            with open(index, encoding="utf-8") as handle:
                html = handle.read()
            if '__SITE_DATA__' in html or '__ACCENT__' in html:
                problems.append("index.html still contains template placeholders")
            if 'id="site-data"' not in html:
                problems.append("index.html has no embedded site-data JSON")
            if "three" not in html:
                problems.append("index.html does not reference three.js")
        except OSError as exc:
            problems.append(f"index.html unreadable: {exc}")
    if not os.path.exists(glb):
        problems.append("product.glb missing")
    else:
        size = os.path.getsize(glb)
        if size < 100:
            problems.append(f"product.glb suspiciously small ({size} bytes)")
        else:
            try:
                with open(glb, "rb") as handle:
                    magic = handle.read(4)
                if magic != b"glTF":
                    problems.append("product.glb is not a binary glTF (bad magic)")
            except OSError as exc:
                problems.append(f"product.glb unreadable: {exc}")
    # LOD tiers: when content.json declares them, every tier GLB must exist.
    try:
        with open(content, encoding="utf-8") as handle:
            declared = (json.load(handle).get("product") or {}).get("lods") or {}
    except (OSError, ValueError):
        declared = {}
    for level, info in declared.items():
        tier_file = (info or {}).get("model") or f"product_{level}.glb"
        tier_path = os.path.join(site_dir, tier_file)
        if not os.path.exists(tier_path):
            problems.append(f"LOD {level} GLB missing: {tier_file}")
            continue
        try:
            with open(tier_path, "rb") as handle:
                if handle.read(4) != b"glTF":
                    problems.append(f"LOD {level} GLB bad magic: {tier_file}")
        except OSError as exc:
            problems.append(f"LOD {level} GLB unreadable: {exc}")
    if not os.path.exists(content):
        problems.append("content.json missing (CMS export)")
        data = {}
    else:
        try:
            with open(content, encoding="utf-8") as handle:
                data = json.load(handle)
            if "locales" not in data:
                problems.append("content.json has no locales")
            if "product" not in data:
                problems.append("content.json has no product block")
        except (OSError, ValueError) as exc:
            problems.append(f"content.json invalid: {exc}")
            data = {}
    # Catalogue / spin / Shopify assets declared in content.json must exist.
    product = data.get("product") or {}
    for image in product.get("images") or []:
        rel = (image or {}).get("file") or ""
        if rel and not os.path.exists(os.path.join(site_dir, rel)):
            problems.append(f"catalogue image missing: {rel}")
    for spin in product.get("spins") or []:
        folder = os.path.join(site_dir, (spin or {}).get("folder") or "")
        amount = int((spin or {}).get("amount") or 0)
        for index in range(1, amount + 1):
            frame = os.path.join(folder, f"frame-{index}.jpg")
            if not os.path.exists(frame):
                problems.append(f"360 frame missing: {spin.get('folder')}frame-{index}.jpg")
                break
    if product.get("variant") == "SHOPIFY":
        for rel in ("shopify/product.json", "shopify/products.csv"):
            if not os.path.exists(os.path.join(site_dir, rel)):
                problems.append(f"Shopify file missing: {rel}")
    if product.get("variant") == "CONFIGURATOR" and not product.get("spins"):
        problems.append("configurator has no 360 spins")
    ar = product.get("ar") or {}
    if ar.get("usdz") and not os.path.exists(os.path.join(site_dir, ar["usdz"])):
        problems.append(f"AR USDZ missing: {ar['usdz']}")
    return problems


def build_manifest(site_dir: str, product: dict, config: dict,
                   port: int, validation: list[str]) -> dict:
    manifest = {
        "product": product,
        "config": config,
        "port": port,
        "url": f"http://127.0.0.1:{port}/",
        "files": {},
        "validation": validation,
        "healthy": not validation,
    }
    for name in ("index.html", "product.glb", "product_high.glb",
                 "product_medium.glb", "product_low.glb", "content.json",
                 "shopify/product.json", "shopify/products.csv"):
        path = os.path.join(site_dir, name)
        if os.path.exists(path):
            manifest["files"][name] = os.path.getsize(path)
    for image in product.get("images") or []:
        rel = (image or {}).get("file") or ""
        path = os.path.join(site_dir, rel) if rel else ""
        if rel and os.path.exists(path):
            manifest["files"][rel] = os.path.getsize(path)
    for spin in product.get("spins") or []:
        folder = (spin or {}).get("folder") or ""
        for index in range(1, int((spin or {}).get("amount") or 0) + 1):
            rel = f"{folder}frame-{index}.jpg"
            path = os.path.join(site_dir, rel)
            if os.path.exists(path):
                manifest["files"][rel] = os.path.getsize(path)
    with open(os.path.join(site_dir, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    return manifest


def serve_command(site_dir: str, port: int) -> str:
    return f"cd {site_dir} && python3 -m http.server {port}"


def write_serve_script(site_dir: str, port: int) -> str:
    """Write serve.py (stdlib only) so the site is one command to run."""
    path = os.path.join(site_dir, "serve.py")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            '"""Serve this showcase folder. Usage: python3 serve.py [port]"""\n'
            "import http.server, socketserver, sys\n"
            f"PORT = int(sys.argv[1]) if len(sys.argv) > 1 else {int(port)}\n"
            'Handler = http.server.SimpleHTTPRequestHandler\n'
            'with socketserver.TCPServer(("", PORT), Handler) as httpd:\n'
            '    print(f"Showcase at http://127.0.0.1:{PORT}/  (Ctrl-C to stop)")\n'
            "    httpd.serve_forever()\n")
    return path
