"""Generate and deploy the Agent Accuracy real-time dashboard.

A KQL dashboard over the EH_AgentEval eventhouse. It exists so that the alert
and the thing you are supposed to do about it are on the same screen. An alert
that says "score dropped" and makes you go and find the reason is an alert
people learn to close.

The remediation queue is the point: it shows the literal instruction text a
human is being asked to approve, next to the question that failed and the
evidence for it.

Schema notes, learned by getting them wrong:

* `schema_version` must match what the portal client expects. Too low and the
  dashboard refuses to load with "Missing migration for dashboard version N".
  The error message names the version it wants.
* Queries are a separate top level array. Tiles reference them by
  `queryRef.queryId`, and each query id must be referenced exactly once.
* Every id must be a real RFC 4122 UUID. Readable strings with dashes in them,
  like "ds-agent-eval", are rejected at load time.

Getting those wrong tends to leave stray dashboards behind, because the fastest
way to find the version the client wants is to create an empty one by hand and
read the error. `Agent Accuracy` is the only KQL dashboard this repo owns. An
empty dashboard with no data sources, queries or tiles is a leftover probe, not
part of the demo, and should be deleted from the workspace.

Ids are generated with uuid5 from a fixed namespace so that re-running this
script produces the same dashboard rather than a new one, which is what keeps
pinned references and share targets intact.

Run:
    python validation/build_dashboard.py
    python validation/build_dashboard.py --print-only
    python validation/build_dashboard.py --recreate
"""

from __future__ import annotations

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
    FABRIC_API,
    KUSTO_DATABASE_NAME as KQL_DATABASE_NAME,
    KUSTO_URI as CLUSTER_URI,
    WORKSPACE_ID,
    require,
)

DASHBOARD_NAME = "Agent Accuracy"

# The version to declare, and it is not the one the portal reports.
#
# The client migrates a dashboard forward from the version in the file to the
# version it currently runs. So the file has to declare a version the client
# has a migration *from*. Declaring the target version fails with "Missing
# migration for dashboard version 78. Required version: 78 Received version:
# 78", which reads like a version mismatch and is not one.
#
# 52 is the version in Microsoft's own REST API example for creating a KQL
# dashboard programmatically, so it is the one with a known migration path.
# Fabric stores whatever it is given without normalising it, which is why this
# has to be right rather than merely plausible.
SCHEMA_VERSION = "52"

NAMESPACE = uuid.UUID("6f1d3f5a-0c7f-4f2e-9c8a-5b1e7d2a4c30")


def stable_id(label: str) -> str:
    """Deterministic UUID, so re-running does not churn the dashboard."""
    return str(uuid.uuid5(NAMESPACE, label))


DATA_SOURCE_ID = stable_id("datasource/eval")
PAGE_ID = stable_id("page/overview")


# --------------------------------------------------------------------------
# Queries
# --------------------------------------------------------------------------

SCORE_TREND = """eval_runs
| order by run_ts asc
| project run_ts, score, max_score"""

LATEST_STATE = """eval_runs
| top 1 by run_ts desc
| project ['Score']=strcat(tostring(score), " / ", tostring(max_score)),
          ['Previous']=previous_score,
          ['Flakes']=flake_count,
          ['Stable failures']=failure_count,
          ['Guardrails lost']=guardrails_lost_count,
          ['Agent errors']=strcat(tostring(error_attempts), " / ", tostring(attempt_count)),
          ['Severity']=alert_severity"""

FLAKE_HISTORY = """eval_runs
| order by run_ts asc
| project run_ts, flake_count, failure_count, guardrails_lost_count"""

OPEN_ALERTS = """eval_runs
| where alert_count > 0
| order by run_ts desc
| take 20
| project run_ts, alert_severity, score, flake_count, failure_count, alert_detail"""

# The tile this dashboard is really for. Anyone approving a change can read
# the exact sentence that will be added, next to the question that failed.
REMEDIATION_QUEUE = """eval_defects
| where isnotempty(proposed_instruction)
| summarize arg_max(run_ts, *) by question_id
| join kind=leftouter (
    eval_approvals
    | summarize arg_max(approved_ts, decision, approved_by, approval_id) by question_id
  ) on question_id
| join kind=leftouter (
    eval_remediations
    | where persisted == true
    | summarize arg_max(recorded_ts, verified) by approval_id
  ) on approval_id
| extend ['Status'] = case(
      isempty(decision), "awaiting approval",
      decision == "rejected", "rejected",
      isempty(approval_id1), "approved, not yet applied",
      verified, "applied and verified",
      "applied, not yet verified")
| project ['Question']=question_id,
          ['Problem']=classification,
          ['Add this to the model AI instructions']=proposed_instruction,
          ['Why']=rationale,
          ['Status'],
          ['Approved by']=approved_by
| order by ['Question'] asc"""

NEEDS_A_HUMAN = """eval_defects
| summarize arg_max(run_ts, *) by question_id
| where tier != 1 or isempty(proposed_instruction)
| project ['Question']=question_id, ['Tier']=tier, ['Problem']=classification,
          ['Fix target']=fix_target, ['Why']=rationale, ['Who acts']=action
| order by ['Tier'] asc, ['Question'] asc"""

APPLIED = """eval_remediations
| order by applied_ts desc
| take 20
| project applied_ts, question_id, approved_by, applied_by, dry_run, persisted,
          verified, instruction"""


def line_options(x_column: str, y_columns: list[str]) -> dict:
    """visualOptions for a time series line chart.

    Unused by default. Every tile ships as a table, because a table renders
    from any result shape and a chart does not: a chart carries column
    bindings that have to survive the client's schema migration, and a tile
    that fails to render takes the whole dashboard with it.

    Add charts from the portal once the dashboard loads, or wire this in and
    re-verify. Do not assume it works.
    """
    return {
        "multipleYAxes": {
            "base": {
                "id": "-1",
                "label": "",
                "columns": [],
                "yAxisMaximumValue": None,
                "yAxisMinimumValue": None,
                "yAxisScale": "linear",
                "horizontalLines": [],
            },
            "additional": [],
            "showMultiplePanels": False,
        },
        "hideLegend": False,
        "legendLocation": "bottom",
        "xColumnTitle": "",
        "xColumn": x_column,
        "yColumns": y_columns,
        "seriesColumns": None,
        "xAxisScale": "linear",
        "verticalLine": "",
    }


# title, query, visualType, visualOptions, x, y, width, height
TILE_SPECS = [
    ("Score over time", SCORE_TREND, "table", {}, 0, 0, 9, 5),
    ("Latest run", LATEST_STATE, "table", {}, 9, 0, 9, 5),
    ("Instability over time", FLAKE_HISTORY, "table", {}, 0, 5, 9, 5),
    ("Alerts raised", OPEN_ALERTS, "table", {}, 9, 5, 9, 5),
    ("Remediation queue, approve or reject each line", REMEDIATION_QUEUE, "table", {},
     0, 10, 18, 7),
    ("Needs a human, no safe automatic fix", NEEDS_A_HUMAN, "table", {}, 0, 17, 9, 5),
    ("Applied remediations", APPLIED, "table", {}, 9, 17, 9, 5),
]


def build_definition() -> dict:
    queries = []
    tiles = []

    for title, text, visual_type, visual_options, x, y, width, height in TILE_SPECS:
        query_id = stable_id(f"query/{title}")
        queries.append({
            "id": query_id,
            "dataSource": {"kind": "inline", "dataSourceId": DATA_SOURCE_ID},
            "text": text,
            "usedVariables": [],
        })
        tiles.append({
            "id": stable_id(f"tile/{title}"),
            "title": title,
            "visualType": visual_type,
            "pageId": PAGE_ID,
            "layout": {"x": x, "y": y, "width": width, "height": height},
            "queryRef": {"kind": "query", "queryId": query_id},
            "visualOptions": visual_options,
        })

    return {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/kqlDashboard/definition/1.0.0/schema.json",
        "id": stable_id("dashboard/agent-accuracy"),
        "schema_version": SCHEMA_VERSION,
        "title": DASHBOARD_NAME,
        # Only `enabled`. At this schema version autoRefresh rejects anything
        # else with "must NOT have unevaluated properties", and adding
        # defaultDuration or minimumDuration is enough to stop the whole
        # dashboard loading. The refresh interval is set in the portal.
        "autoRefresh": {"enabled": True},
        "baseQueries": [],
        "parameters": [],
        "dataSources": [{
            "id": DATA_SOURCE_ID,
            "name": KQL_DATABASE_NAME,
            "clusterUri": CLUSTER_URI,
            "database": KQL_DATABASE_NAME,
            "kind": "manual-kusto",
            "scopeId": "kusto",
        }],
        "pages": [{"id": PAGE_ID, "name": "Overview"}],
        "queries": queries,
        "tiles": tiles,
    }


def validate(definition: dict) -> list[str]:
    """The checks the load endpoint makes, run here where they are cheap.

    Every one of these corresponds to a real load failure, which is why they
    are worth doing before deploying rather than reading about in a modal.
    """
    problems = []

    def is_uuid(value) -> bool:
        try:
            uuid.UUID(str(value))
            return True
        except (ValueError, AttributeError, TypeError):
            return False

    # The schema rejects unknown properties outright, with "must NOT have
    # unevaluated properties". A single extra key anywhere stops the whole
    # dashboard loading, so the allowed sets are pinned here rather than
    # discovered one modal at a time.
    allowed = {
        "autoRefresh": {"enabled"},
        "tile": {"id", "title", "visualType", "pageId", "layout", "queryRef",
                 "visualOptions"},
        "query": {"id", "dataSource", "text", "usedVariables"},
        "dataSource": {"id", "name", "clusterUri", "database", "kind", "scopeId"},
        "page": {"id", "name"},
    }

    extra = set(definition.get("autoRefresh", {})) - allowed["autoRefresh"]
    if extra:
        problems.append(f"autoRefresh has unsupported propertie(s): {sorted(extra)}")

    for section, key in (("tiles", "tile"), ("queries", "query"),
                         ("dataSources", "dataSource"), ("pages", "page")):
        for entry in definition[section]:
            unexpected = set(entry) - allowed[key]
            if unexpected:
                problems.append(
                    f"{section}: {entry.get('title') or entry.get('id')} has "
                    f"unsupported propertie(s): {sorted(unexpected)}"
                )

    for section in ("tiles", "queries", "dataSources", "pages"):
        seen = set()
        for entry in definition[section]:
            entry_id = entry.get("id")
            if not is_uuid(entry_id):
                problems.append(f"{section}: id {entry_id!r} is not an RFC 4122 UUID")
            if entry_id in seen:
                problems.append(f"{section}: duplicate id {entry_id}")
            seen.add(entry_id)

    query_ids = {q["id"] for q in definition["queries"]}
    referenced = [t["queryRef"]["queryId"] for t in definition["tiles"]]

    for query_id in referenced:
        if query_id not in query_ids:
            problems.append(f"tile references unknown query {query_id}")
    for query_id in query_ids:
        count = referenced.count(query_id)
        if count != 1:
            problems.append(f"query {query_id} referenced {count} times, must be once")

    page_ids = {p["id"] for p in definition["pages"]}
    for tile in definition["tiles"]:
        if tile["pageId"] not in page_ids:
            problems.append(f"tile {tile['title']!r} points at an unknown page")

    source_ids = {d["id"] for d in definition["dataSources"]}
    for query in definition["queries"]:
        if query["dataSource"]["dataSourceId"] not in source_ids:
            problems.append(f"query {query['id']} points at an unknown data source")

    return problems


# --------------------------------------------------------------------------
# Fabric REST
# --------------------------------------------------------------------------

def token() -> str:
    result = subprocess.run(
        ["az", "account", "get-access-token", "--resource", FABRIC_API,
         "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, shell=True, check=True,
    )
    return result.stdout.strip()


def call(method: str, url: str, body: dict | None = None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {token()}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read().decode("utf-8")
            # A 202 can carry a literal "null" body, which json.loads turns
            # into None rather than a dict, so every caller that reads an id
            # off it would raise AttributeError instead of polling.
            payload = json.loads(raw) if raw.strip() else {}
            return response.status, (payload or {}), dict(response.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} {method} {url}\n{raw[:1500]}") from None


def wait(operation_id: str) -> None:
    for _ in range(60):
        _, payload, _ = call("GET", f"{FABRIC_API}/v1/operations/{operation_id}")
        status = payload.get("status")
        if status == "Succeeded":
            return
        if status in {"Failed", "Undetermined"}:
            raise SystemExit(f"operation {operation_id} {status}: {payload}")
        time.sleep(5)
    raise SystemExit("operation did not finish")


def find_existing() -> str | None:
    _, payload, _ = call(
        "GET", f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}/items?type=KQLDashboard"
    )
    for item in payload.get("value", []):
        if item.get("displayName") == DASHBOARD_NAME:
            return item["id"]
    return None


def main() -> int:
    definition_json = build_definition()
    problems = validate(definition_json)
    if problems:
        print("dashboard definition is invalid:")
        for problem in problems:
            print(f"  {problem}")
        return 1

    if "--print-only" in sys.argv:
        print(json.dumps(definition_json, indent=2))
        return 0

    require("FABRIC_WORKSPACE_ID", "FABRIC_KUSTO_URI")

    print(f"definition valid: {len(definition_json['tiles'])} tiles, "
          f"schema_version {SCHEMA_VERSION}")

    encoded = base64.b64encode(
        json.dumps(definition_json, indent=2).encode("utf-8")
    ).decode("utf-8")
    definition = {"parts": [{
        "path": "RealTimeDashboard.json",
        "payload": encoded,
        "payloadType": "InlineBase64",
    }]}

    existing = find_existing()

    if existing and "--recreate" in sys.argv:
        print(f"deleting existing dashboard {existing}")
        call("DELETE", f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}/items/{existing}")
        existing = None
        time.sleep(5)

    if existing:
        print(f"updating dashboard {existing}")
        status, _, headers = call(
            "POST",
            f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}/items/{existing}/updateDefinition",
            {"definition": definition},
        )
        dashboard_id = existing
    else:
        print("creating dashboard")
        # A soft deleted item holds its display name for a few minutes, so a
        # recreate immediately after a delete gets a retriable 409.
        for attempt in range(12):
            try:
                status, payload, headers = call(
                    "POST", f"{FABRIC_API}/v1/workspaces/{WORKSPACE_ID}/items",
                    {
                        "displayName": DASHBOARD_NAME,
                        "description": (
                            "Data agent accuracy: score, instability, alerts, and "
                            "the remediation queue with the exact instruction text "
                            "awaiting approval."
                        ),
                        "type": "KQLDashboard",
                        "definition": definition,
                    },
                )
                break
            except SystemExit as exc:
                if "ItemDisplayNameNotAvailableYet" not in str(exc) or attempt == 11:
                    raise
                print(f"  name not free yet, retrying in 30s ({attempt + 1}/12)")
                time.sleep(30)
        dashboard_id = payload.get("id")

    if status == 202:
        wait(headers.get("x-ms-operation-id"))
        dashboard_id = dashboard_id or find_existing()

    print(f"dashboard ready: {dashboard_id}")
    print(f"https://app.powerbi.com/groups/{WORKSPACE_ID}/kustodashboards/{dashboard_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
