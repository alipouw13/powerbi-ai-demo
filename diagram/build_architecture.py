#!/usr/bin/env python3
"""Generate the Power BI AI lifecycle architecture diagram.

Writes two files next to this script:

  powerbi-ai-demo-architecture.drawio   editable, official icons embedded
  powerbi-ai-demo-architecture.svg      standalone, for rendering

Run render.py afterwards to produce powerbi-ai-demo-architecture.png.

Icons come from the official Microsoft Azure and Fabric icon sets through
`cloudicons.py`, embedded as base64 so the output is self-contained. Point
AZURE_ICONS_DIR and FABRIC_ICONS_DIR at your local copies first, see
diagram/README.md.

Usage:
    python diagram/build_architecture.py
    python diagram/render.py diagram/powerbi-ai-demo-architecture.svg --png-only
"""
from __future__ import annotations

import base64
import html
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cloudicons as ci  # noqa: E402

# ----------------------------------------------------------------- design
INK = "#121A3E"
NAVY = "#1E2761"
SLATE = "#5A6683"
MUTED = "#7E88A6"
RULE = "#DDE3F0"
PAPER = "#F7F8FC"
WHITE = "#FFFFFF"
AMBER = "#F2A900"
AMBER_DK = "#8A5A00"
AMBER_BG = "#FFF6E3"
TEAL = "#00A896"
TEAL_BG = "#E6F7F4"

W, H = 1660, 880
COL_W, COL_GAP = 372, 40
COL_X0, COL_Y = 40, 138
CARD_H, CARD_GAP, PAD = 76, 14, 18
HDR_H = 54
COL_H = HDR_H + 4 * CARD_H + 3 * CARD_GAP + 2 * PAD  # tallest column wins

BAND_Y = COL_Y + COL_H + 54
BAND_H = 156

# --------------------------------------------------------------- content
# icon = (query, provider). None means a text-only card, which is deliberate:
# a gate and an accuracy loop are processes, not products, so they get no
# product icon.
COLUMNS = [
    {
        "title": "Authoring plane",
        "meta": "Phases 0 to 3",
        "accent": NAVY,
        "note": "Your machine. Nothing here is a Fabric item.",
        "cards": [
            ("VS Code", ["The editor you already use"], ("code", "azure")),
            ("GitHub Copilot", ["Writes the notebook, the DAX,", "and the descriptions"],
             ("github copilot", "brand")),
            ("MCP servers (preview)", ["Fabric MCP, Power BI Modeling MCP.", "Chat that can act on the tenant"],
             ("api connections", "azure")),
            ("Power BI Desktop", ["Modelling, plus DAX query view", "with Copilot"],
             ("power bi", "fabric")),
        ],
    },
    {
        "title": "Fabric workspace",
        "meta": "Phases 1 to 3",
        "accent": NAVY,
        "note": "Created from a chat prompt, not the portal.",
        "cards": [
            ("Lakehouse", ["Four delta tables, one star schema"], ("lakehouse", "fabric")),
            ("Notebook", ["Ingests the CSVs with explicit schemas"], ("notebook", "fabric")),
            ("Semantic model", ["21 measures, every object described"],
             ("semantic model", "fabric")),
            ("OneLake", ["One copy of the data underneath", "every item above"],
             ("onelake", "fabric")),
        ],
    },
    {
        "title": "Make it AI ready",
        "meta": "Gate 3b, then phase 4",
        "accent": AMBER,
        "note": "The step almost everyone skips.",
        "cards": [
            ("Gate 3b, readiness audit", ["Score the model against the Copilot",
                                          "optimization checklist. No AI involved."], None),
            ("Prep data for AI (preview)", ["AI instructions, AI data schema,",
                                            "verified answers"], ("copilot", "fabric")),
            ("Approved for Copilot (preview)", ["Marks the model as trusted for AI"], None),
            ("PBIP and TMDL", ["AI instructions live in source control,",
                               "reviewable in a pull request"],
             ("semantic model", "fabric")),
        ],
    },
    {
        "title": "Consumption",
        "meta": "Phases 5 to 7",
        "accent": TEAL,
        "note": "Four front doors onto one governed model.",
        "cards": [
            ("Power BI report", ["Pages built by Copilot from a prompt"], ("report", "fabric")),
            ("Copilot, in report and standalone", ["In report is GA, standalone is preview"],
             ("copilot", "fabric")),
            ("Fabric data agent", ["Serves the semantic model,", "and nothing else, to any conversation"],
             ("data agent", "fabric")),
            ("Fabric IQ ontology (preview)", ["Business meaning above the model"],
             ("ontology", "fabric")),
        ],
    },
]

BAND_CARDS = [
    ("Question bank", "15 questions with known answers, plus 3 written to fail"),
    ("Ground truth", "One script computes every expected value from the CSVs"),
    ("Scorecard", "Pass A before phase 4, pass B after. The gap is the argument."),
]

FLOW = [
    "Build the model with AI, but score the model before you score the AI.",
    "Every front door on the right reads the same semantic model, so a fix lands once.",
    "When an answer is wrong, the fix goes into the model, never into the question.",
]


# ------------------------------------------------------------ icon lookup
_cache: dict[str, list] = {}
_missing: list[str] = []


def icon(spec):
    """Resolve (query, provider) to (base64 data uri, draw.io style). None if absent."""
    if spec is None:
        return None
    query, provider = spec
    if provider not in _cache:
        idx, warn = ci.build_index(provider, ci.DEFAULT_AZURE, ci.DEFAULT_FABRIC,
                                   ci.DEFAULT_BRAND)
        for w in warn:
            print("  warning: " + w)
        _cache[provider] = idx
    hits = ci.search(_cache[provider], query, 1)
    if not hits:
        _missing.append(f"{query} ({provider})")
        return None
    path = Path(hits[0]["path"])
    mime = ci._RASTER_MIME.get(path.suffix.lower(), "image/svg+xml")
    uri = f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
    return uri, ci.STYLE + uri


# ----------------------------------------------------------------- layout
def col_x(i):
    return COL_X0 + i * (COL_W + COL_GAP)


def card_y(row):
    return COL_Y + HDR_H + PAD + row * (CARD_H + CARD_GAP)


# -------------------------------------------------------------- svg build
def esc(s):
    return html.escape(s, quote=True)


def svg_text(x, y, s, size, color, weight="normal", anchor="start", style=""):
    fs = f'font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="{size}"'
    fw = f' font-weight="{weight}"' if weight != "normal" else ""
    ta = f' text-anchor="{anchor}"' if anchor != "start" else ""
    st = f' {style}' if style else ""
    return f'<text x="{x}" y="{y}" {fs}{fw} fill="{color}"{ta}{st}>{esc(s)}</text>'


def svg_rect(x, y, w, h, fill, stroke=None, r=0, sw=1, dash=None):
    s = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" ry="{r}" fill="{fill}"'
    if stroke:
        s += f' stroke="{stroke}" stroke-width="{sw}"'
        if dash:
            s += f' stroke-dasharray="{dash}"'
    return s + "/>"


def build_svg():
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" '
         f'xmlns:xlink="http://www.w3.org/1999/xlink" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}">']
    o.append(svg_rect(0, 0, W, H, PAPER))
    o.append(svg_rect(0, 0, W, 6, AMBER))

    o.append(svg_text(COL_X0, 62, "Power BI AI lifecycle", 30, INK, "700"))
    o.append(svg_text(COL_X0, 92,
                      "Build, publish, use and score a semantic model with AI, "
                      "then prove the score moved", 15, SLATE))
    o.append(svg_text(W - COL_X0, 62, "Contoso Coffee", 15, MUTED, anchor="end"))
    o.append(svg_text(W - COL_X0, 84, "synthetic data, 64,335 rows", 12, MUTED, anchor="end"))

    for i, c in enumerate(COLUMNS):
        x = col_x(i)
        o.append(svg_rect(x, COL_Y, COL_W, COL_H, WHITE, RULE, r=12))
        o.append(f'<path d="M{x + 12} {COL_Y} h{COL_W - 24} a12 12 0 0 1 12 12 v-12 z" '
                 f'fill="{c["accent"]}"/>')
        o.append(svg_rect(x, COL_Y, COL_W, 5, c["accent"]))
        o.append(svg_text(x + PAD, COL_Y + 30, c["title"], 17, INK, "700"))
        o.append(svg_text(x + COL_W - PAD, COL_Y + 29, c["meta"], 11.5, c["accent"],
                          "700", anchor="end"))
        o.append(svg_text(x + PAD, COL_Y + 47, c["note"], 11, MUTED))

        for r, (title, subs, ispec) in enumerate(c["cards"]):
            y = card_y(r)
            cw = COL_W - 2 * PAD
            res = icon(ispec)
            plain = res is None
            fill = AMBER_BG if plain and c["accent"] == AMBER else WHITE
            stroke = AMBER if plain and c["accent"] == AMBER else RULE
            o.append(svg_rect(x + PAD, y, cw, CARD_H, fill, stroke, r=8))
            tx = x + PAD + 16
            if res:
                o.append(f'<image x="{x + PAD + 14}" y="{y + 18}" width="40" height="40" '
                         f'xlink:href="{res[0]}"/>')
                tx = x + PAD + 66
            else:
                o.append(svg_rect(x + PAD, y, 5, CARD_H, c["accent"]))
                tx = x + PAD + 18
            o.append(svg_text(tx, y + (28 if len(subs) > 1 else 34), title, 13.5, INK, "700"))
            for k, sub in enumerate(subs):
                o.append(svg_text(tx, y + (46 if len(subs) > 1 else 52) + k * 15,
                                  sub, 11, SLATE))

    # arrows between columns
    ay = COL_Y + COL_H / 2
    for i in range(len(COLUMNS) - 1):
        x1 = col_x(i) + COL_W + 6
        x2 = col_x(i + 1) - 6
        o.append(f'<line x1="{x1}" y1="{ay}" x2="{x2 - 9}" y2="{ay}" stroke="{MUTED}" '
                 f'stroke-width="2"/>')
        o.append(f'<path d="M{x2} {ay} l-10 -6 v12 z" fill="{MUTED}"/>')

    # accuracy loop band
    o.append(svg_rect(COL_X0, BAND_Y, W - 2 * COL_X0, BAND_H, WHITE, TEAL, r=12))
    o.append(svg_rect(COL_X0, BAND_Y, W - 2 * COL_X0, 5, TEAL))
    o.append(svg_text(COL_X0 + PAD, BAND_Y + 32, "The accuracy loop", 17, INK, "700"))
    o.append(svg_text(COL_X0 + PAD, BAND_Y + 52,
                      "Phase 8. Not a product, a habit.", 11, MUTED))
    bx = COL_X0 + 300
    bw = (W - 2 * COL_X0 - 300 - PAD - 2 * 16) / 3
    for k, (t, s) in enumerate(BAND_CARDS):
        x = bx + k * (bw + 16)
        o.append(svg_rect(x, BAND_Y + 26, bw, 104, TEAL_BG, TEAL, r=8))
        o.append(svg_text(x + 16, BAND_Y + 54, t, 13.5, INK, "700"))
        words, line, lines = s.split(), "", []
        for wd in words:
            trial = (line + " " + wd).strip()
            if len(trial) > 44:
                lines.append(line)
                line = wd
            else:
                line = trial
        lines.append(line)
        for j, ln in enumerate(lines[:3]):
            o.append(svg_text(x + 16, BAND_Y + 76 + j * 16, ln, 11, SLATE))

    # feedback arrow: the loop feeds the model, not the prompt
    fx = col_x(2) + COL_W / 2
    o.append(f'<path d="M{COL_X0 + 150} {BAND_Y} V{BAND_Y - 26} H{fx} V{COL_Y + COL_H + 10}" '
             f'fill="none" stroke="{TEAL}" stroke-width="2" stroke-dasharray="6 5"/>')
    o.append(f'<path d="M{fx} {COL_Y + COL_H + 2} l-6 10 h12 z" fill="{TEAL}"/>')
    o.append(svg_text(fx + 14, BAND_Y - 32, "Fixes go into the model", 11.5, TEAL, "700"))

    for k, line in enumerate(FLOW):
        o.append(svg_text(COL_X0, BAND_Y + BAND_H + 30 + k * 19,
                          f"{k + 1}.  {line}", 12, SLATE))
    o.append(svg_text(W - COL_X0, BAND_Y + BAND_H + 68,
                      "Preview features are labelled. Re-check before you commit to a date.",
                      11, MUTED, anchor="end"))
    o.append("</svg>")
    return "\n".join(o)


# ----------------------------------------------------------- drawio build
def cell(cid, value, style, x, y, w, h, parent="1"):
    return (f'        <mxCell id="{cid}" value="{esc(value)}" style="{style}" '
            f'vertex="1" parent="{parent}">\n'
            f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/>\n'
            f'        </mxCell>')


def build_drawio():
    o = ['<mxfile host="powerbi-ai-demo">',
         '  <diagram name="Power BI AI lifecycle">',
         f'    <mxGraphModel dx="{W}" dy="{H}" grid="1" gridSize="10" page="1" '
         f'pageWidth="{W}" pageHeight="{H}" background="{PAPER}">',
         '      <root>',
         '        <mxCell id="0"/>',
         '        <mxCell id="1" parent="0"/>']
    box = ("rounded=1;arcSize=8;whiteSpace=wrap;html=1;verticalAlign=top;align=left;"
           "spacingLeft=12;spacingTop=8;fontSize={fs};fontStyle=1;fontColor={fc};"
           "fillColor={fill};strokeColor={sc};")
    o.append(cell("title", "Power BI AI lifecycle",
                  "text;html=1;align=left;verticalAlign=middle;fontSize=28;fontStyle=1;"
                  f"fontColor={INK};", COL_X0, 30, 700, 40))
    o.append(cell("sub", "Build, publish, use and score a semantic model with AI, "
                         "then prove the score moved",
                  f"text;html=1;align=left;verticalAlign=middle;fontSize=14;fontColor={SLATE};",
                  COL_X0, 70, 900, 26))

    anchors = []
    for i, c in enumerate(COLUMNS):
        x = col_x(i)
        o.append(cell(f"col{i}", f"{c['title']}\n{c['meta']}",
                      box.format(fs=15, fc=INK, fill=WHITE, sc=RULE) +
                      f"strokeWidth=1;", x, COL_Y, COL_W, COL_H))
        o.append(cell(f"col{i}bar", "",
                      f"rounded=0;fillColor={c['accent']};strokeColor=none;",
                      x, COL_Y, COL_W, 5))
        anchors.append(f"col{i}")
        for r, (t, subs, ispec) in enumerate(c["cards"]):
            y, cw = card_y(r), COL_W - 2 * PAD
            res = icon(ispec)
            cid = f"c{i}_{r}"
            label = t + "\n" + " ".join(subs)
            if res:
                o.append(cell(cid + "_bg", "",
                              box.format(fs=12, fc=INK, fill=WHITE, sc=RULE),
                              x + PAD, y, cw, CARD_H))
                o.append(cell(cid + "_ic", "", res[1], x + PAD + 14, y + 18, 40, 40))
                o.append(cell(cid, label,
                              "text;html=1;align=left;verticalAlign=middle;fontSize=11;"
                              f"fontColor={INK};", x + PAD + 62, y + 8, cw - 74, CARD_H - 16))
            else:
                o.append(cell(cid, label,
                              box.format(fs=12, fc=INK, fill=AMBER_BG, sc=AMBER),
                              x + PAD, y, cw, CARD_H))

    o.append(cell("band", "The accuracy loop\nPhase 8. Not a product, a habit.",
                  box.format(fs=15, fc=INK, fill=WHITE, sc=TEAL),
                  COL_X0, BAND_Y, W - 2 * COL_X0, BAND_H))
    bx = COL_X0 + 300
    bw = int((W - 2 * COL_X0 - 300 - PAD - 32) / 3)
    for k, (t, s) in enumerate(BAND_CARDS):
        o.append(cell(f"b{k}", f"{t}\n{s}",
                      box.format(fs=12, fc=INK, fill=TEAL_BG, sc=TEAL),
                      bx + k * (bw + 16), BAND_Y + 26, bw, 104))

    for i in range(len(COLUMNS) - 1):
        o.append(f'        <mxCell id="e{i}" style="edgeStyle=orthogonalEdgeStyle;'
                 f'rounded=0;html=1;strokeColor={MUTED};strokeWidth=2;endArrow=block;" '
                 f'edge="1" parent="1" source="{anchors[i]}" target="{anchors[i + 1]}">\n'
                 f'          <mxGeometry relative="1" as="geometry"/>\n        </mxCell>')
    o.append(f'        <mxCell id="efb" value="Fixes go into the model" '
             f'style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor={TEAL};'
             f'strokeWidth=2;dashed=1;endArrow=block;fontSize=11;fontColor={TEAL};" '
             f'edge="1" parent="1" source="band" target="col2">\n'
             f'          <mxGeometry relative="1" as="geometry"/>\n        </mxCell>')

    o += ['      </root>', '    </mxGraphModel>', '  </diagram>', '</mxfile>']
    return "\n".join(o)


def main():
    svg_path = HERE / "powerbi-ai-demo-architecture.svg"
    dio_path = HERE / "powerbi-ai-demo-architecture.drawio"
    svg = build_svg()
    dio = build_drawio()
    if _missing:
        raise SystemExit("Icons not resolved, check AZURE_ICONS_DIR / FABRIC_ICONS_DIR:\n  "
                         + "\n  ".join(sorted(set(_missing))))
    svg_path.write_text(svg, encoding="utf-8")
    dio_path.write_text(dio, encoding="utf-8")
    print(f"  -> {svg_path.name}  ({len(svg) // 1024} KB)")
    print(f"  -> {dio_path.name}  ({len(dio) // 1024} KB)")
    print("  next: python diagram/render.py diagram/"
          "powerbi-ai-demo-architecture.svg --png-only")


if __name__ == "__main__":
    main()
