"""Build the AgentEvals report, in the shape of the Contoso Coffee report.

The loop now writes its state to a SQL database and a Direct Lake model sits
over it, so the accuracy story can be read in a Power BI report. This builds
that report, as a translytical task flow: read the evidence on page one,
decide on page two, and the decision goes back to SQL through a user data
function.

The structure is deliberately the same as the product-reviews translytical
demo, because the shapes are the same:

    Product              ->  Question
    Review and sentiment ->  Answer and its Grade
    Agent comment        ->  Proposed Instruction, written by the harness
    Employee comment     ->  Approval Decision and Note, written by a person
    Responded flag       ->  Persisted, then Verified

One difference is kept on purpose. In the reviews demo the employee comment
*is* the outcome. Here approving only records a decision: the remediation
notebook applies it and a later run proves it worked. Page two shows those
three states separately, because collapsing them would let the report claim a
fix that nobody has written and nothing has verified.

The visual language is lifted from the Contoso Coffee report so the two feel
like one product: 1280x720, a #4C7DF0 header band, five KPI cards at y=100 on
a 243px pitch, and two content rows.

Run:
    python validation/build_agentevals_report.py            # write PBIR locally
    python validation/build_agentevals_report.py --apply    # push it to Fabric
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (  # noqa: E402
    AGENTEVALS_MODEL_NAME,
    AGENTEVALS_REPORT_NAME,
    FABRIC_API,
    WORKSPACE_ID,
    require,
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "semantic-model" / "agentevals" / "report"

NAMESPACE = uuid.UUID("6f1d3f5a-0c7f-4f2e-9c8a-5b1e7d2a4c30")

# --------------------------------------------------------------------------
# The grid, taken from the Contoso Coffee report rather than invented
# --------------------------------------------------------------------------

CANVAS_W, CANVAS_H = 1280, 720
HEADER_H = 88
CARD_Y, CARD_H, CARD_W = 100, 140, 227
CARD_X = [40, 283, 526, 769, 1012]
ROW2_Y, ROW2_H = 256, 208
ROW3_Y, ROW3_H = 478, 202
HALF_W = 592
RIGHT_X = 648
FULL_W = 1200

BLUE = "#4C7DF0"
PAGE_BG = "#F5F6FA"
OUTSPACE = "#EDEFF5"
CARD_BORDER = "#E8EAF2"
MUTED = "#5A6178"
SHADOW = "#8B92A8"

# Accent colours for the KPI cards, in the order they appear.
GOOD, WARN, BAD, INFO, NEUTRAL = "#2FB37F", "#F0A93C", "#F4585C", BLUE, "#8B92A8"


def vid(label: str) -> str:
    """Deterministic 20 hex character id, the shape PBIR uses."""
    return uuid.uuid5(NAMESPACE, f"agentevals-report/{label}").hex[:20]


# --------------------------------------------------------------------------
# Expression helpers
# --------------------------------------------------------------------------
#
# PBIR wraps every formatting value in an expression. Strings carry their own
# single quotes, integers take an L suffix, booleans are bare. Getting this
# wrong does not error, it silently drops the property, so these exist so that
# no literal is ever hand-written below.

def lit(value: str | int | bool) -> dict:
    if isinstance(value, bool):
        raw = "true" if value else "false"
    elif isinstance(value, int):
        raw = f"{value}L"
    else:
        raw = f"'{value}'"
    return {"expr": {"Literal": {"Value": raw}}}


def colour(value: str) -> dict:
    return {"solid": {"color": lit(value)}}


def props(**kwargs) -> list[dict]:
    return [{"properties": dict(kwargs)}]


def measure(table: str, name: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": table}},
                        "Property": name}}


def column(table: str, name: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}},
                       "Property": name}}


def projection(field: dict, table: str, name: str, active: bool | None = None) -> dict:
    out = {"field": field, "queryRef": f"{table}.{name}", "nativeQueryRef": name}
    if active is not None:
        out["active"] = active
    return out


# --------------------------------------------------------------------------
# Container chrome
# --------------------------------------------------------------------------
#
# The white rounded card with a soft shadow. Every tile on both pages uses it,
# which is most of why the report looks like the Contoso Coffee one.

def card_chrome(title: str | None, *, font_size: int = 12,
                upper: bool = False) -> dict:
    chrome: dict = {
        "background": props(show=lit(True), color=colour("#FFFFFF"),
                            transparency=lit(0)),
        "border": props(show=lit(True), color=colour(CARD_BORDER), radius=lit(8)),
        "dropShadow": props(
            show=lit(True), preset=lit("Custom"), color=colour(SHADOW),
            shadowSpread=lit(0), shadowBlur=lit(8), angle=lit(90),
            shadowDistance=lit(2), transparency=lit(88),
        ),
    }
    if title is not None:
        chrome["title"] = props(
            show=lit(True),
            text=lit(title.upper() if upper else title),
            fontColor=colour(MUTED),
            fontFamily=lit("Segoe UI Semibold"),
            fontSize=lit(font_size),
            alignment=lit("left"),
        )
    return chrome


def visual(name: str, x: int, y: int, w: int, h: int, body: dict,
           z: int = 1, filters: list | None = None) -> dict:
    out = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/"
                   "report/definition/visualContainer/2.11.0/schema.json",
        "name": name,
        "position": {"x": x, "y": y, "z": z, "width": w, "height": h},
        "visual": body,
    }
    if filters:
        out["filterConfig"] = {"filters": filters}
    return out


# --------------------------------------------------------------------------
# Visual builders
# --------------------------------------------------------------------------

def header_band(page: str) -> dict:
    return visual(
        vid(f"{page}/band"), 0, 0, CANVAS_W, HEADER_H, z=0,
        body={
            "visualType": "shape",
            "objects": {
                "fill": props(show=lit(True), fillColor=colour(BLUE),
                              transparency=lit(0)),
                "outline": props(show=lit(False)),
            },
            "visualContainerObjects": {
                "background": props(show=lit(True), color=colour(BLUE),
                                    transparency=lit(0)),
                "border": props(show=lit(False)),
                "dropShadow": props(show=lit(False)),
            },
            "drillFilterOtherVisuals": True,
        },
    )


def header_title(page: str, text: str) -> dict:
    return visual(
        vid(f"{page}/title"), 40, 20, 620, 48, z=2,
        body={
            "visualType": "textbox",
            "objects": {
                "general": [{"properties": {"paragraphs": [{
                    "textRuns": [{
                        "value": text,
                        "textStyle": {"fontFamily": "Segoe UI",
                                      "fontSize": "14pt",
                                      "fontWeight": "bold",
                                      "color": "#FFFFFF"},
                    }],
                    "horizontalTextAlignment": "left",
                }]}}],
            },
            "visualContainerObjects": {
                "background": props(show=lit(False)),
                "border": props(show=lit(False)),
            },
            "drillFilterOtherVisuals": True,
        },
    )


def slicer(page: str, key: str, table: str, field: str, x: int) -> dict:
    return visual(
        vid(f"{page}/slicer/{key}"), x, 12, 212, 64, z=2,
        body={
            "visualType": "slicer",
            "query": {"queryState": {"Values": {"projections": [
                projection(column(table, field), table, field, active=True)
            ]}}},
            "objects": {
                "data": props(mode=lit("Dropdown")),
                "header": props(show=lit(True), fontFamily=lit("Segoe UI"),
                                textSize=lit(9), fontColor=colour(MUTED)),
                "selection": props(selectAllCheckboxEnabled=lit(True)),
            },
            "drillFilterOtherVisuals": True,
        },
        filters=[{"name": vid(f"{page}/slicerfilter/{key}"),
                  "field": column(table, field), "type": "Categorical"}],
    )


def kpi_card(page: str, key: str, table: str, name: str, title: str,
             accent: str, x: int) -> dict:
    return visual(
        vid(f"{page}/card/{key}"), x, CARD_Y, CARD_W, CARD_H,
        body={
            "visualType": "cardVisual",
            "query": {"queryState": {"Data": {"projections": [
                projection(measure(table, name), table, name)
            ]}}},
            "objects": {
                "accentBar": [{
                    "properties": {"show": lit(True), "color": colour(accent)},
                    "selector": {"metadata": f"{table}.{name}"},
                }],
                "outline": props(show=lit(False)),
                "layout": props(maxTiles=lit(1)),
            },
            "visualContainerObjects": card_chrome(title, font_size=9, upper=True),
            "drillFilterOtherVisuals": True,
        },
    )


def chart(page: str, key: str, chart_type: str, title: str,
          x: int, y: int, w: int, h: int, roles: dict,
          sort: dict | None = None) -> dict:
    query: dict = {"queryState": {}}
    for role, fields in roles.items():
        query["queryState"][role] = {"projections": [
            projection(field, table, name,
                       active=True if role == "Category" and i == 0 else None)
            for i, (field, table, name) in enumerate(fields)
        ]}
    if sort:
        query["sortDefinition"] = {"sort": [sort]}
    return visual(
        vid(f"{page}/chart/{key}"), x, y, w, h,
        body={
            "visualType": chart_type,
            "query": query,
            "visualContainerObjects": card_chrome(title),
            "drillFilterOtherVisuals": True,
        },
    )


def table_visual(page: str, key: str, title: str, x: int, y: int, w: int,
                 h: int, columns: list[tuple[dict, str, str]]) -> dict:
    return visual(
        vid(f"{page}/table/{key}"), x, y, w, h,
        body={
            "visualType": "tableEx",
            "query": {"queryState": {"Values": {"projections": [
                projection(field, table, name)
                for field, table, name in columns
            ]}}},
            "objects": {
                "grid": props(gridVertical=lit(True),
                              gridVerticalColor=colour(CARD_BORDER),
                              gridHorizontal=lit(True),
                              gridHorizontalColor=colour(CARD_BORDER)),
                "columnHeaders": props(fontColor=colour(MUTED),
                                       fontFamily=lit("Segoe UI Semibold"),
                                       fontSize=lit(9)),
                "values": props(fontSize=lit(9), wordWrap=lit(True)),
            },
            "visualContainerObjects": card_chrome(title),
            "drillFilterOtherVisuals": True,
        },
    )


def input_slicer(page: str, key: str, title: str, x: int, y: int,
                 w: int, h: int) -> dict:
    """An input slicer with no data column, so it is an input rather than a filter.

    This is the control the user data function reads. With a column bound it
    would filter the page instead, which is a different visual doing a
    different job.
    """
    return visual(
        vid(f"{page}/input/{key}"), x, y, w, h, z=3,
        body={
            "visualType": "textSlicer",
            "objects": {
                "data": props(mode=lit("Input")),
            },
            "visualContainerObjects": card_chrome(title),
            "drillFilterOtherVisuals": True,
        },
    )


def state(id_: str = "default", **kwargs) -> dict:
    """A formatting block for one button state.

    Button properties are per state, so text and fill without a selector are
    accepted and then ignored. The button renders as an empty outline, which
    is how the first version of this page shipped.
    """
    return {"properties": dict(kwargs), "selector": {"id": id_}}


def action_button(page: str, key: str, text: str, x: int, y: int,
                  w: int, h: int) -> dict:
    """The button the data function is bound to.

    Two things about this are worth knowing before you look at it.

    The **action binding is not written here**. It names a workspace, a
    function set and a function by id, which are tenant facts this repo keeps
    out of source control, and the parameter mapping is authored in the format
    pane. See semantic-model/agentevals/report.md.

    The **label and fill may not appear until that binding is done**. Fabric
    stores the text and fill blocks below exactly as given, and a rendered
    export ignores them while `outline` is honoured. Four property shapes were
    published and exported to find that out; all four rendered the same. So
    the button is given a strong outline, which does render, and the label is
    set in the format pane during the same pass that binds the function.
    """
    return visual(
        vid(f"{page}/button/{key}"), x, y, w, h, z=3,
        body={
            "visualType": "actionButton",
            "objects": {
                "text": [
                    state(show=lit(True), text=lit(text),
                          fontColor=colour("#FFFFFF"),
                          fontFamily=lit("Segoe UI Semibold"),
                          fontSize=lit(11),
                          horizontalAlignment=lit("center")),
                    # The loading state is unique to data function buttons. A
                    # button that looks identical while the function runs gets
                    # clicked twice, and twice writes two rows.
                    state("loading", show=lit(True), text=lit("Submitting"),
                          fontColor=colour("#FFFFFF"),
                          fontFamily=lit("Segoe UI Semibold"),
                          fontSize=lit(11),
                          horizontalAlignment=lit("center")),
                ],
                "fill": [
                    state(show=lit(True), fillColor=colour(BLUE),
                          transparency=lit(0)),
                    state("loading", show=lit(True),
                          fillColor=colour("#3A63C4"), transparency=lit(0)),
                    state("disabled", show=lit(True),
                          fillColor=colour("#C7CDDB"), transparency=lit(0)),
                ],
                # The one thing that renders, so it is what makes the button
                # look deliberate rather than broken.
                "outline": [state(show=lit(True), lineColor=colour(BLUE),
                                  weight=lit(2), transparency=lit(0))],
            },
            "visualContainerObjects": {
                "dropShadow": props(show=lit(True), preset=lit("Custom"),
                                    color=colour(SHADOW), shadowSpread=lit(0),
                                    shadowBlur=lit(8), angle=lit(90),
                                    shadowDistance=lit(2), transparency=lit(80)),
            },
            "drillFilterOtherVisuals": True,
        },
    )


def note_box(page: str, key: str, text: str, x: int, y: int,
             w: int, h: int) -> dict:
    return visual(
        vid(f"{page}/note/{key}"), x, y, w, h, z=2,
        body={
            "visualType": "textbox",
            "objects": {
                "general": [{"properties": {"paragraphs": [{
                    "textRuns": [{
                        "value": text,
                        "textStyle": {"fontFamily": "Segoe UI",
                                      "fontSize": "9pt",
                                      "color": MUTED},
                    }],
                    "horizontalTextAlignment": "left",
                }]}}],
            },
            "visualContainerObjects": {
                "background": props(show=lit(False)),
                "border": props(show=lit(False)),
            },
            "drillFilterOtherVisuals": True,
        },
    )


# --------------------------------------------------------------------------
# Page one: the evidence
# --------------------------------------------------------------------------
#
# The equivalent of the product reviews page. A question is the product, an
# answer is the review, and the Grade is the sentiment.

P1 = "quality"
P1_NAME = vid("page/quality")


def page_one() -> list[dict]:
    return [
        header_band(P1),
        header_title(P1, "Agent Answer Quality"),
        slicer(P1, "surface", "Evaluation Runs", "Surface", 800),
        slicer(P1, "kind", "Questions", "Question Kind", 1028),

        kpi_card(P1, "score", "Evaluation Runs", "Score Headline",
                 "Latest score", INFO, CARD_X[0]),
        kpi_card(P1, "pct", "Evaluation Runs", "Score %",
                 "Score %", GOOD, CARD_X[1]),
        kpi_card(P1, "flaky", "Evaluation Runs", "Flaky Questions",
                 "Flaky questions", WARN, CARD_X[2]),
        kpi_card(P1, "failing", "Evaluation Runs", "Failing Questions",
                 "Failing questions", BAD, CARD_X[3]),
        kpi_card(P1, "guardrails", "Evaluation Runs", "Guardrails Lost",
                 "Guardrails lost", BAD, CARD_X[4]),

        # Which question, and how it was graded. The stacked bars are the
        # point: a question with two colours is a flake, and a flake is the
        # finding a single run cannot produce.
        chart(P1, "byquestion", "clusteredBarChart",
              "Attempts by question and grade", 40, ROW2_Y, HALF_W, ROW2_H,
              roles={
                  "Category": [(column("Questions", "Question ID"),
                                "Questions", "Question ID")],
                  "Y": [(measure("Answers", "Attempts"), "Answers", "Attempts")],
                  "Series": [(column("Answers", "Grade"), "Answers", "Grade")],
              },
              sort={"field": column("Questions", "Question ID"),
                    "direction": "Ascending"}),

        chart(P1, "bygrade", "donutChart", "Attempts by grade",
              RIGHT_X, ROW2_Y, HALF_W, ROW2_H,
              roles={
                  "Category": [(column("Answers", "Grade"), "Answers", "Grade")],
                  "Y": [(measure("Answers", "Attempts"), "Answers", "Attempts")],
              }),

        # The review list. One fact table per visual: a table that mixed
        # Answers with Defects would ask Power BI to relate an attempt to a
        # proposed fix, and there is no path between those rows. It renders as
        # "can't determine relationships between the fields", which is how
        # this layout was found to be wrong the first time.
        table_visual(P1, "answers", "Questions and how they were answered",
                     40, ROW3_Y, 780, ROW3_H, columns=[
                         (column("Questions", "Question ID"),
                          "Questions", "Question ID"),
                         (column("Questions", "Question Text"),
                          "Questions", "Question Text"),
                         (column("Answers", "Question Outcome"),
                          "Answers", "Question Outcome"),
                         (column("Answers", "Grade"), "Answers", "Grade"),
                         (column("Answers", "Answer Text"),
                          "Answers", "Answer Text"),
                     ]),

        # The harness's own comment on each question, alongside rather than
        # inside the answer list, for the reason above.
        table_visual(P1, "proposed", "What the harness proposes to fix it",
                     836, ROW3_Y, 404, ROW3_H, columns=[
                         (column("Questions", "Question ID"),
                          "Questions", "Question ID"),
                         (column("Defects", "Defect Outcome"),
                          "Defects", "Defect Outcome"),
                         (column("Defects", "Proposed Instruction"),
                          "Defects", "Proposed Instruction"),
                     ]),
    ]


# --------------------------------------------------------------------------
# Page two: the decision, and the writeback
# --------------------------------------------------------------------------

P2 = "approve"
P2_NAME = vid("page/approve")

ACTION_Y = 462
ACTION_H = 242

GUARDRAIL = (
    "Approving writes one row to dbo.approvals through the user data "
    "function, and nothing else. Your name comes from your sign-in, not from "
    "a field. A pipeline mirrors the row to the eventhouse, the remediation "
    "notebook applies the sentence, and the next evaluation run is what says "
    "whether it worked. Approved, applied and verified are three different "
    "things, and the cards above count them separately."
)


def page_two() -> list[dict]:
    return [
        header_band(P2),
        header_title(P2, "Review & Approve Fixes"),
        slicer(P2, "question", "Questions", "Question ID", 800),
        slicer(P2, "target", "Defects", "Instruction Target", 1028),

        kpi_card(P2, "open", "Defects", "Defects In Latest Run",
                 "Defects in latest run", WARN, CARD_X[0]),
        kpi_card(P2, "await", "Approvals", "Awaiting Apply",
                 "Awaiting apply", INFO, CARD_X[1]),
        kpi_card(P2, "approved", "Approvals", "Approved",
                 "Approved", GOOD, CARD_X[2]),
        kpi_card(P2, "rejected", "Approvals", "Rejected",
                 "Rejected", NEUTRAL, CARD_X[3]),
        kpi_card(P2, "verified", "Remediations", "Verified Fix %",
                 "Verified fix %", GOOD, CARD_X[4]),

        # The queue. Select a row to choose the question the button acts on.
        table_visual(P2, "queue", "Proposed fixes awaiting a decision",
                     40, ROW2_Y - 16, 780, 206, columns=[
                         (column("Questions", "Question ID"),
                          "Questions", "Question ID"),
                         (column("Questions", "Question Text"),
                          "Questions", "Question Text"),
                         (column("Defects", "Defect Outcome"),
                          "Defects", "Defect Outcome"),
                         (column("Defects", "Fix Tier"), "Defects", "Fix Tier"),
                         (column("Defects", "Proposed Instruction"),
                          "Defects", "Proposed Instruction"),
                     ]),

        # What has already been written back. This is the employee comments
        # panel in the reviews demo, and it is the proof the loop closed.
        table_visual(P2, "decided", "Decisions already written back",
                     836, ROW2_Y - 16, 404, 206, columns=[
                         (column("Questions", "Question ID"),
                          "Questions", "Question ID"),
                         (column("Approvals", "Decision"),
                          "Approvals", "Decision"),
                         (column("Approvals", "Decided By"),
                          "Approvals", "Decided By"),
                         (column("Approvals", "Decision Note"),
                          "Approvals", "Decision Note"),
                     ]),

        input_slicer(P2, "decision", "Decision (approved or rejected)",
                     40, ACTION_Y, 370, 84),
        input_slicer(P2, "note", "Note for the record",
                     426, ACTION_Y, 394, 84),
        # The caption carries the label until the format pane does. A button
        # whose text has not rendered is indistinguishable from a broken one,
        # and this page is asking somebody to change a production model.
        note_box(P2, "submit", "Then submit your decision:", 40, 548, 220, 28),
        action_button(P2, "submit", "Submit decision", 40, 578, 200, 44),
        note_box(P2, "guardrail", GUARDRAIL, 260, 556, 560, 96),

        chart(P2, "bytier", "donutChart", "Defects by fix tier",
              836, ACTION_Y, 404, ACTION_H,
              roles={
                  "Category": [(column("Defects", "Fix Tier"),
                                "Defects", "Fix Tier")],
                  "Y": [(measure("Defects", "Defects Found"),
                         "Defects", "Defects Found")],
              }),
    ]


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

PAGES = [
    (P1_NAME, "Agent Answer Quality", page_one),
    (P2_NAME, "Review & Approve Fixes", page_two),
]


def page_json(name: str, display: str) -> dict:
    return {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/"
                   "report/definition/page/2.1.0/schema.json",
        "name": name,
        "displayName": display,
        "displayOption": "FitToPage",
        "height": CANVAS_H,
        "width": CANVAS_W,
        "objects": {
            "background": props(color=colour(PAGE_BG), transparency=lit(0)),
            "outspace": props(color=colour(OUTSPACE), transparency=lit(0)),
        },
    }


def build(model_id: str, base_theme: str) -> dict[str, str]:
    parts: dict[str, str] = {}

    def add(path: str, payload: dict) -> None:
        parts[path] = json.dumps(payload, indent=2)

    add("definition.pbir", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/"
                   "report/definitionProperties/2.0.0/schema.json",
        "version": "4.0",
        "datasetReference": {"byConnection": {
            "connectionString":
                'Data Source="powerbi://api.powerbi.com/v1.0/myorg/'
                f'{WORKSPACE_NAME}";initial catalog={AGENTEVALS_MODEL_NAME};'
                f"integrated security=ClaimsToken;semanticmodelid={model_id}",
        }},
    })

    add("definition/version.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/"
                   "report/definition/versionMetadata/1.0.0/schema.json",
        "version": "2.0.0",
    })

    add("definition/report.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/"
                   "report/definition/report/3.3.0/schema.json",
        "themeCollection": {"baseTheme": {
            "name": base_theme,
            "reportVersionAtImport": {"visual": "2.12.0", "report": "3.4.0",
                                      "page": "2.3.1"},
            "type": "SharedResources",
        }},
        "objects": {
            "section": props(verticalAlignment=lit("Top")),
            "outspacePane": props(expanded=lit(False)),
        },
        "resourcePackages": [{
            "name": "SharedResources", "type": "SharedResources",
            "items": [{"name": base_theme,
                       "path": f"BaseThemes/{base_theme}.json",
                       "type": "BaseTheme"}],
        }],
        "settings": {
            "useStylableVisualContainerHeader": True,
            "exportDataMode": "AllowSummarized",
            "defaultDrillFilterOtherVisuals": True,
            "allowChangeFilterTypes": True,
            "useEnhancedTooltips": True,
            "useDefaultAggregateDisplayName": True,
        },
    })

    add("definition/pages/pages.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/"
                   "report/definition/pagesMetadata/1.1.0/schema.json",
        "pageOrder": [name for name, _, _ in PAGES],
        "activePageName": PAGES[0][0],
    })

    for name, display, builder in PAGES:
        add(f"definition/pages/{name}/page.json", page_json(name, display))
        for item in builder():
            add(f"definition/pages/{name}/visuals/{item['name']}/visual.json",
                item)

    return parts


# --------------------------------------------------------------------------
# Fabric REST
# --------------------------------------------------------------------------

WORKSPACE_NAME = ""  # resolved at run time, never committed


def token() -> str:
    result = subprocess.run(
        ["az", "account", "get-access-token", "--resource", FABRIC_API,
         "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, shell=True, check=True,
    )
    return result.stdout.strip()


def call(method: str, url: str, body: dict | None = None) -> tuple[int, dict, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {token()}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            raw = response.read().decode("utf-8")
            return response.status, (json.loads(raw) if raw.strip() else {}), \
                dict(response.headers)
    except urllib.error.HTTPError as exc:
        raise SystemExit(
            f"HTTP {exc.code} {method} {url}\n"
            + exc.read().decode("utf-8", errors="replace")[:1500]
        ) from None


def find_item(item_type: str, name: str) -> str | None:
    _, payload, _ = call(
        "GET", f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}/items?type={item_type}")
    for item in payload.get("value", []):
        if item.get("displayName") == name:
            return item["id"]
    return None


def wait(headers: dict) -> None:
    operation_id = headers.get("x-ms-operation-id")
    if not operation_id:
        return
    for _ in range(60):
        _, state, _ = call("GET", f"{FABRIC_API}/v1/operations/{operation_id}")
        status = state.get("status")
        if status == "Succeeded":
            return
        if status in {"Failed", "Undetermined"}:
            raise SystemExit(f"update failed: {state}")
        time.sleep(5)
    raise SystemExit("timed out waiting for the update to finish")


def existing_base_theme(report_id: str) -> str:
    """Reuse whatever base theme the report already carries.

    The base theme name is a platform version, CY26SU08 today, and a report
    that names one the tenant does not have fails to open. Reading it is a
    request; guessing it is a support ticket.
    """
    _, _, headers = call(
        "POST", f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}/reports/"
                f"{report_id}/getDefinition")
    operation_id = headers.get("x-ms-operation-id")
    for _ in range(60):
        _, state, _ = call("GET", f"{FABRIC_API}/v1/operations/{operation_id}")
        if state.get("status") == "Succeeded":
            break
        if state.get("status") in {"Failed", "Undetermined"}:
            raise SystemExit(f"could not read the report: {state}")
        time.sleep(5)
    _, result, _ = call(
        "GET", f"{FABRIC_API}/v1/operations/{operation_id}/result")
    for part in result.get("definition", {}).get("parts", []):
        if part["path"] == "definition/report.json":
            report = json.loads(base64.b64decode(part["payload"]))
            return report["themeCollection"]["baseTheme"]["name"]
    raise SystemExit("the report has no base theme to reuse")


def apply(report_id: str, parts: dict[str, str]) -> int:
    print(f"updating {AGENTEVALS_REPORT_NAME} ({report_id}) "
          f"with {len(parts)} parts")
    _, _, headers = call(
        "POST",
        f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}/reports/"
        f"{report_id}/updateDefinition",
        {"definition": {"parts": [
            {"path": path,
             "payload": base64.b64encode(text.encode("utf-8")).decode("ascii"),
             "payloadType": "InlineBase64"}
            for path, text in parts.items()
        ]}},
    )
    wait(headers)
    print("applied")
    return 0


def write_local(parts: dict[str, str]) -> None:
    for path, text in parts.items():
        target = OUT / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    print(f"wrote {len(parts)} parts to {OUT.relative_to(ROOT)}")


def main() -> int:
    global WORKSPACE_NAME

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="push the definition to the report in Fabric")
    args = parser.parse_args()

    require("FABRIC_WORKSPACE_ID")

    _, workspace, _ = call("GET", f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}")
    WORKSPACE_NAME = workspace["displayName"]

    model_id = find_item("SemanticModel", AGENTEVALS_MODEL_NAME)
    if not model_id:
        raise SystemExit(
            f"no semantic model called {AGENTEVALS_MODEL_NAME}. Run "
            "python validation/build_agentevals_model.py --apply first.")

    report_id = find_item("Report", AGENTEVALS_REPORT_NAME)
    if not report_id:
        raise SystemExit(
            f"no report called {AGENTEVALS_REPORT_NAME} in this workspace. "
            "Create an empty one over the AgentEvals model first, or set "
            "FABRIC_AGENTEVALS_REPORT_NAME.")

    base_theme = existing_base_theme(report_id)
    parts = build(model_id, base_theme)
    write_local(parts)
    return apply(report_id, parts) if args.apply else 0


if __name__ == "__main__":
    sys.exit(main())
