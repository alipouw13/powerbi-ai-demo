#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Vendored unmodified from the drawio-skill diagramming tooling.
"""Find Microsoft Azure + Microsoft Fabric product icons as draw.io styles.

draw.io ships AWS/Azure stencils, but they are dated and have NO Microsoft
Fabric item icons (Lakehouse, Warehouse, Eventhouse, KQL DB, Notebook,
Pipeline, Semantic model, ...). This resolves a service name to a draw.io
`image` style whose icon is the official local SVG, embedded as a base64 data
URI so the diagram is fully self-contained (offline-safe, no CDN).

Icon sources (local, override with env vars):
  - Azure  : C:\\Users\\<you>\\Azure_Public_Service_Icons   (AZURE_ICONS_DIR)
             Official "Azure Public Service Icons" set, ~700 service SVGs in
             Icons/<category>/NNNNN-icon-service-<Name>.svg
  - Fabric : C:\\Users\\<you>\\Fabric_Icons                 (FABRIC_ICONS_DIR)
             @fabric-msft/svg-icons NPM package, ~1600 SVGs, flat,
             <name>_<size>_<variant>.svg  (variant: item | non-item | filled | regular)

Usage:
  python3 cloudicons.py "azure sql"
  python3 cloudicons.py "fabric lakehouse" --provider fabric
  python3 cloudicons.py "salesforce" --provider brand
  python3 cloudicons.py "synapse" --json
  python3 cloudicons.py "data factory" --embed-off   # reference local file:// instead of embedding
  python3 cloudicons.py --list --provider fabric | more

A third provider, "brand", resolves vendored third-party logos (Salesforce,
Snowflake, ...) from a local "brand-icons/" folder next to this script, so they
are always available without any env var. PNG and SVG are both supported.

Output: a draw.io `image=` style string (default embeds the icon). Drop it on a
node's `style=`; set the node label to the service name.

Icons are trademarks of Microsoft, referenced for identification only - the
same basis on which draw.io ships AWS/Azure stencils.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path

STYLE = ("shape=image;html=1;imageAspect=0;aspect=fixed;"
         "verticalLabelPosition=bottom;verticalAlign=top;image=")

# Default local roots; override with env vars so the skill is portable.
DEFAULT_AZURE = os.environ.get(
    "AZURE_ICONS_DIR",
    str(Path.home() / "Azure_Public_Service_Icons"),
)
DEFAULT_FABRIC = os.environ.get(
    "FABRIC_ICONS_DIR",
    str(Path.home() / "Fabric_Icons"),
)
# Vendored third-party brand logos (Salesforce, Snowflake, ...). Lives next to
# this script so it is ALWAYS available without any env var or external set.
DEFAULT_BRAND = os.environ.get(
    "BRAND_ICONS_DIR",
    str(Path(__file__).resolve().parent / "brand-icons"),
)

_RASTER_MIME = {".svg": "image/svg+xml", ".png": "image/png",
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}

# Fabric icons come in many sizes; prefer this order when several match.
_FABRIC_SIZE_PREF = ["48", "64", "40", "32", "24", "20", "16", "12"]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _collapse(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _azure_label(path: Path) -> str:
    # 00606-icon-service-Azure-Synapse-Analytics.svg -> "Azure Synapse Analytics"
    name = path.stem
    name = re.sub(r"^\d+-", "", name)
    name = re.sub(r"^icon-service-", "", name)
    name = name.replace("-", " ").replace("(", "").replace(")", "")
    return re.sub(r"\s+", " ", name).strip()


def _fabric_label(path: Path) -> str:
    # lakehouse_48_item.svg -> "lakehouse" ; copy_job_24_item -> "copy job"
    name = path.stem
    name = re.sub(r"_\d+_(item|non-item|filled|regular|color)$", "", name)
    name = re.sub(r"_(item|non-item|filled|regular|color)$", "", name)
    name = re.sub(r"_\d+$", "", name)
    return name.replace("_", " ").strip()


def _fabric_meta(path: Path):
    m = re.search(r"_(\d+)_(item|non-item|filled|regular|color)$", path.stem)
    size = m.group(1) if m else "0"
    variant = m.group(2) if m else ""
    return size, variant


def _brand_label(path: Path) -> str:
    # salesforce.png -> "salesforce" ; sql_server.png -> "sql server"
    return re.sub(r"\s+", " ", path.stem.replace("_", " ").replace("-", " ")).strip()


def _index_brand(root: Path):
    items = []
    for p in sorted(root.iterdir()):
        if p.suffix.lower() in _RASTER_MIME:
            label = _brand_label(p)
            items.append({"provider": "brand", "label": label, "category": "brand",
                          "path": str(p), "tokens": set(_norm(label).split())})
    return items


def _index_azure(root: Path):
    items = []
    icons = root / "Icons"
    base = icons if icons.is_dir() else root
    for p in base.rglob("*.svg"):
        label = _azure_label(p)
        items.append({"provider": "azure", "label": label,
                      "category": p.parent.name, "path": str(p),
                      "tokens": set(_norm(label).split())})
    return items


def _index_fabric(root: Path):
    # Collapse the size variants: keep the best (largest, item-preferred) per name.
    by_name = {}
    for p in root.glob("*.svg"):
        label = _fabric_label(p)
        size, variant = _fabric_meta(p)
        key = label
        score = (1 if variant == "item" else 0, _FABRIC_SIZE_PREF.index(size)
                 if size in _FABRIC_SIZE_PREF else 99)
        # lower size-index = larger; prefer item, then larger size
        cur = by_name.get(key)
        cand = (-(score[0]), score[1], p, label, variant, size)
        if cur is None or cand < cur:
            by_name[key] = cand
    items = []
    for key, (_, _, p, label, variant, size) in by_name.items():
        items.append({"provider": "fabric", "label": label, "category": variant,
                      "path": str(p), "size": size,
                      "tokens": set(_norm(label).split())})
    return items


def build_index(providers, azure_dir, fabric_dir, brand_dir=None):
    idx = []
    warn = []
    if providers in ("azure", "all"):
        ar = Path(azure_dir)
        if ar.is_dir():
            idx += _index_azure(ar)
        else:
            warn.append(f"Azure icons dir not found: {azure_dir} (set AZURE_ICONS_DIR)")
    if providers in ("fabric", "all"):
        fr = Path(fabric_dir)
        if fr.is_dir():
            idx += _index_fabric(fr)
        else:
            warn.append(f"Fabric icons dir not found: {fabric_dir} (set FABRIC_ICONS_DIR)")
    if providers in ("brand", "all"):
        br = Path(brand_dir or DEFAULT_BRAND)
        if br.is_dir():
            idx += _index_brand(br)
        elif providers == "brand":
            warn.append(f"Brand icons dir not found: {br} (set BRAND_ICONS_DIR)")
    return idx, warn


def search(idx, query, limit):
    q = _norm(query)
    qc = _collapse(query)
    qtoks = set(q.split())
    if not qtoks:
        return []
    scored = []
    for it in idx:
        lab = _norm(it["label"])
        lc = _collapse(it["label"])
        toks = it["tokens"]
        overlap = len(qtoks & toks)
        extra = max(0, len(toks) - len(qtoks))
        score = 0
        if q == lab or qc == lc:
            score = 1000
        elif lab.startswith(q) or lc.startswith(qc):
            score = 700 - extra
        elif qc and qc in lc:
            score = 500 - extra
        elif qtoks <= toks:                      # all query words present as tokens
            score = 400 - extra
        elif overlap >= 2:                       # multi-word partial
            score = 150 * overlap - extra
        elif overlap == 1 and len(qtoks) == 1:   # single-word query, weak single hit
            score = 60 - extra
        # Fabric "item" icons are the canonical product glyphs - tiny tiebreak,
        # applied only to genuine matches (never promotes a zero-score row).
        if score > 0 and it["provider"] == "fabric" and it.get("category") == "item":
            score += 4
        if score > 0:
            scored.append((score, it))
    scored.sort(key=lambda x: (-x[0], len(x[1]["tokens"]), len(x[1]["label"])))
    return [it for _, it in scored[:limit]]


def embed_style(path, embed=True):
    p = Path(path)
    if not embed:
        return STYLE + p.resolve().as_uri()
    data = p.read_bytes()
    mime = _RASTER_MIME.get(p.suffix.lower(), "image/svg+xml")
    return STYLE + f"data:{mime};base64," + base64.b64encode(data).decode()


def main():
    ap = argparse.ArgumentParser(
        description="Find Azure + Fabric product icons as draw.io image styles (local SVGs).")
    ap.add_argument("query", nargs="?", default="", help="service name, e.g. 'azure sql' or 'lakehouse'")
    ap.add_argument("--provider", choices=["azure", "fabric", "brand", "all"], default="all")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--size", type=int, default=64, help="node w/h in px (default 64)")
    ap.add_argument("--embed-off", action="store_true",
                    help="reference the local file via file:// instead of embedding base64")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list", action="store_true", help="list all icons for the provider(s)")
    ap.add_argument("--azure-dir", default=DEFAULT_AZURE)
    ap.add_argument("--fabric-dir", default=DEFAULT_FABRIC)
    ap.add_argument("--brand-dir", default=DEFAULT_BRAND)
    args = ap.parse_args()

    idx, warn = build_index(args.provider, args.azure_dir, args.fabric_dir, args.brand_dir)
    for w in warn:
        print(f"warning: {w}", file=sys.stderr)
    if not idx:
        print("error: no icons indexed (check icon dirs / env vars)", file=sys.stderr)
        sys.exit(2)

    if args.list:
        rows = sorted(idx, key=lambda x: (x["provider"], x["label"]))
        if args.json:
            print(json.dumps([{"provider": r["provider"], "label": r["label"],
                               "category": r.get("category", "")} for r in rows], indent=2))
        else:
            for r in rows:
                print(f'{r["provider"]:<7} {r["label"]}')
        print(f"\n{len(rows)} icons", file=sys.stderr)
        return

    if not args.query:
        ap.error("provide a query, or use --list")

    hits = search(idx, args.query, args.limit)
    if not hits:
        print(f"No icon matched '{args.query}'. Try --list to browse, or broaden the query.",
              file=sys.stderr)
        sys.exit(1)

    results = []
    for h in hits:
        style = embed_style(h["path"], embed=not args.embed_off)
        results.append({"provider": h["provider"], "label": h["label"],
                        "category": h.get("category", ""), "path": h["path"],
                        "w": args.size, "h": args.size, "style": style})

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            shown = r["style"] if len(r["style"]) < 140 else r["style"][:137] + "..."
            print(f'[{r["provider"]}] {r["label"]}')
            print(f'  style: {shown}')
            print(f'  w/h:   {r["w"]}x{r["h"]}   src: {r["path"]}')
        print(f'\n{len(results)} match(es). Use --json for full embeddable styles.',
              file=sys.stderr)


if __name__ == "__main__":
    main()
