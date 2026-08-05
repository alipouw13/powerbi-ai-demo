# SPDX-License-Identifier: MIT
# Vendored from the drawio-skill diagramming tooling.
"""Render an .svg to .png (2x raster) and .pdf using headless Chrome.

No draw.io desktop CLI is required on the host. We wrap the standalone SVG that
build_architecture.py emits into a minimal HTML page sized to the diagram and
let Chrome rasterize / print it. Usage:

    python diagram/render.py diagram/powerbi-ai-demo-architecture.svg
    python diagram/render.py diagram/powerbi-ai-demo-architecture.svg --png-only
"""
import os
import re
import subprocess
import sys
import tempfile
import time

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_chrome():
    env = os.environ.get("CHROME_BIN")
    if env and os.path.exists(env):
        return env
    for c in CHROME_CANDIDATES:
        if os.path.exists(c):
            return c
    raise SystemExit("Chrome/Edge not found - set CHROME_BIN")


def dims(svg_text):
    w = re.search(r'width="(\d+)"', svg_text)
    h = re.search(r'height="(\d+)"', svg_text)
    return int(w.group(1)), int(h.group(1))


def render(svg_path, png_only=False, scale=2):
    chrome = find_chrome()
    svg = open(svg_path, encoding="utf-8").read()
    w, h = dims(svg)
    base = os.path.abspath(os.path.splitext(svg_path)[0])
    html = (f'<!doctype html><html><head><meta charset="utf-8">'
            f'<style>html,body{{margin:0;padding:0;background:#F7FAFD}}'
            f'svg{{display:block}}</style></head><body>{svg}</body></html>')
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        html_path = f.name
        f.write(html)
    prof = tempfile.mkdtemp(prefix="chrome-prof-")
    common = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
              f"--user-data-dir={prof}", "--hide-scrollbars"]
    png = base + ".png"

    def _run(args, out_path, timeout=60):
        """Launch Chrome headless, poll for the output file, then force-kill the
        process tree. Chrome headless on Windows reliably WRITES the screenshot
        but often does not EXIT, and subprocess timeouts don't always reap its
        child tree - so we poll for a stable output file and taskkill by PID."""
        if os.path.exists(out_path):
            os.remove(out_path)
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + timeout
        last = -1
        while time.time() < deadline:
            if proc.poll() is not None:          # exited on its own
                break
            if os.path.exists(out_path):
                sz = os.path.getsize(out_path)
                if sz > 0 and sz == last:        # file written and stable
                    break
                last = sz
            time.sleep(0.5)
        if proc.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return os.path.exists(out_path) and os.path.getsize(out_path) > 0

    ok = _run(common + [f"--screenshot={png}", f"--window-size={w},{h}",
                        f"--force-device-scale-factor={scale}",
                        "--default-background-color=FFF7FAFD",
                        f"file:///{html_path.replace(os.sep, '/')}"], png)
    print(f"  -> {os.path.basename(png)}" + ("" if ok else "  [FAILED]"))
    if not png_only:
        pdf = base + ".pdf"
        ok_pdf = _run(common + [f"--print-to-pdf={pdf}", "--no-pdf-header-footer",
                                f"file:///{html_path.replace(os.sep, '/')}"], pdf)
        print(f"  -> {os.path.basename(pdf)}" + ("" if ok_pdf else "  [FAILED]"))
    os.unlink(html_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    render(sys.argv[1], png_only="--png-only" in sys.argv)
